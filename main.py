
import io
import os
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Union
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from fastapi.middleware.cors import CORSMiddleware

# 建立 FastAPI 應用
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發階段設為 "*" 代表允許所有來源 (包含直接點開 HTML 檔案)
    allow_credentials=True,
    allow_methods=["*"],  # 允許所有 HTTP 方法 (GET, POST, etc.)
    allow_headers=["*"],  # 允許所有標頭
    expose_headers=["Content-Disposition"], # 重要：讓前端能讀取檔名 (Content-Disposition)
)

# 加入例外處理器，當發生 422 錯誤時印出詳細資訊到終端機
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

# --- 資料模型定義 ---
# 定義從前端接收的資料結構，這應該與 counsel_form.html 中的 form 物件對應
class CounselFormData(BaseModel):
    name: Optional[str] = ""
    gender: Optional[str] = ""
    dob: Optional[str] = ""
    idNumber: Optional[str] = ""
    address: Optional[str] = ""
    date: Optional[str] = ""
    sessionNumber: Optional[Union[str, int]] = ""
    format: Optional[str] = ""
    teleCounselingType: Optional[str] = ""
    complaints: List[str] = Field(default_factory=list)
    familyIssueType: Optional[str] = ""
    complaintOther: Optional[str] = ""
    goals: List[str] = Field(default_factory=list)
    goalOther: Optional[str] = ""
    plans: List[str] = Field(default_factory=list)
    planOther: Optional[str] = ""
    summary: Optional[str] = ""
    signature: Optional[str] = ""

# --- PDF 欄位對應 ---
# 將前端的選項對應到 PDF 的欄位名稱
# 注意：這需要根據 get_pdf_fields.py 的輸出來手動匹配
# 對於 Checkbox，值設置為 '/Yes' 表示勾選
CHECKBOX_MAP = {
    # 諮商形式
    "01.個別諮商": "checkbox_single",
    "02.伴侶/家族諮商": "checkbox_couple_family",
    "03.親子/兒童諮商": "checkbox_parent_child",
    "04.通訊心理諮商": "checkbox_remote",
    "04.通訊心理諮商-個別": "checkbox_remote_single",
    "04.通訊心理諮商-伴侶": "checkbox_remote_couple",
    "04.通訊心理諮商-家族": "checkbox_remote_family",
    # 個案主訴
    "01.經濟問題": "problem_economic",
    "02.就業工作": "problem_work",
    "03.生涯規劃": "problem_life_plan",
    "04.醫療健康的心理問題": "problem_health_mental",
    "05.自我認識": "problem_self",
    "06.情感困擾": "problem_relation",
    "07.行為困擾": "problem_action",
    "08.重大失落或生活變故": "problem_deep_loss",
    "09.一般資訊": "problem_normal",
    "10.學習問題": "problem_learning",
    "11.人際關係": "problem_people_relation",
    "12.壓力與情緒困擾": "problem_pressure",
    "13.家庭暴力": "problem_home_violence",
    "14.自殺／傷": "problem_suicide",
    "15.性侵害": "problem_sex_harassment",
    "16.性議題": "problem_sex",
    "17.死亡/悲傷": "problem_death",
    "18.家庭議題": "problem_family",
    "18.家庭議題-家庭": "problem_family_family",
    "18.家庭議題-子女教養": "problem_family_child",
    "18.家庭議題-夫妻": "problem_family_couple",
    "18.家庭議題-親子": "problem_family_parent_child",
    "19.其他": "problem_others",
    # 治療目標
    "01.建立關係": "treat_work_focus", # 假設名稱
    "02.聚焦工作目標": "treat_work_focus", # 假設名稱
    "03.提高自我覺察": "treat_self_awareness",
    "04.降低挫折": "treat_remove_ frustration",
    "05.梳理過去經驗": "treat_experience",
    "06.改善人際關係": "treat_relation",
    "07.提升情緒管理能力": "treat_emotion_management",
    "08.增加因應能力策略": "treat_capability",
    "09.提升環境適應技巧": "treat_environment",
    "10.其他": "treat_others",
    # 處置規劃
    "01.目標設定": "dipose_target",
    "02.同理與支持": "dipose_empath",
    "03.經驗整合": "dipose_experience",
    "04.內在聚焦": "dipose_internal",
    "05.自我探索": "dipose_self_explore",
    "06.賦權與賦能": "dipose_talent",
    "07.情感宣洩": "dipose_emotional",
    "08.重新框架": "dipose_restructure",
    "09.訊息提供": "dipose_message",
    "10.結案準備": "dipose_end",
    "11.其他": "dipose_others",
}

@app.post("/fill_pdf")
async def fill_pdf_endpoint(data: CounselFormData):
    """
    接收前端傳來的 JSON 資料，填寫到 PDF 表單中，並回傳產生的 PDF。
    """
    template_path = "counsel_form_empty_fill_v2.pdf"

    if not os.path.exists(template_path):
        raise HTTPException(status_code=500, detail=f"找不到 PDF 模板檔案: {template_path}，請確認檔案位於正確路徑。")

    # 使用 clone_from 初始化，這樣會保留原始 PDF 的表單結構 (/AcroForm)
    writer = PdfWriter(clone_from=template_path)

    # --- 設定欄位屬性：開啟多行 (Multiline) 模式 ---
    # 針對長文字欄位設定 Flag 4096 (Multiline)，讓文字能自動換行
    fields_to_multiline = ["counsel_content", "problem_others_text", "treat_others_text", "dipose_others_text"]
    page = writer.pages[0]
    if "/Annots" in page:
        for annot in page["/Annots"]:
            annot_obj = annot.get_object()
            if annot_obj.get("/T") in fields_to_multiline:
                current_flags = int(annot_obj.get("/Ff", 0))
                annot_obj[NameObject("/Ff")] = NumberObject(current_flags | 4096)

    # --- 建立欄位資料字典 ---
    pdf_data = {
        "name": data.name,
        "id_number": data.idNumber,
        "address": data.address,
        "counsel_time": str(data.sessionNumber),
        "problem_others_text": data.complaintOther,
        "treat_others_text": data.goalOther,
        "dipose_others_text": data.planOther,
        "counsel_content": data.summary,
        "signature": data.signature
    }

    # 處理性別
    if data.gender:
         pdf_data["gender"] = data.gender

    # 處理日期
    if data.dob:
        try:
            year, month, day = data.dob.split('-')
            roc_year = int(year) - 1911
            pdf_data['birth_date_year'] = str(roc_year)
            pdf_data['birth_date_month'] = month
            pdf_data['birth_date_date'] = day
        except ValueError:
            print(f"Error parsing DOB: {data.dob}")

    if data.date:
        try:
            year, month, day = data.date.split('-')
            roc_year = int(year) - 1911
            pdf_data['counsel_date_year'] = str(roc_year)
            pdf_data['counsel_date_month'] = month
            pdf_data['counsel_date_date'] = day
        except ValueError:
            print(f"Error parsing Date: {data.date}")

    # 處理 Checkbox
    if data.format:
        for item in data.format.split(','): #
            if item in CHECKBOX_MAP:
                pdf_data[CHECKBOX_MAP[item]] = '/Yes'

    # 處理通訊諮商子選項 (個別/伴侶/家族)
    if data.format == "04.通訊心理諮商" and data.teleCounselingType:
        key = f"04.通訊心理諮商-{data.teleCounselingType}"
        if key in CHECKBOX_MAP:
            pdf_data[CHECKBOX_MAP[key]] = '/Yes'

    # 處理家庭議題子選項 (家庭/子女教養/夫妻/親子)
    if "18.家庭議題" in data.complaints and data.familyIssueType:
        key = f"18.家庭議題-{data.familyIssueType}"
        if key in CHECKBOX_MAP:
            pdf_data[CHECKBOX_MAP[key]] = '/Yes'

    for item in data.complaints:
        if item in CHECKBOX_MAP:
            pdf_data[CHECKBOX_MAP[item]] = '/Yes'

    for item in data.goals:
        if item in CHECKBOX_MAP:
            pdf_data[CHECKBOX_MAP[item]] = '/Yes'

    for item in data.plans:
        if item in CHECKBOX_MAP:
            pdf_data[CHECKBOX_MAP[item]] = '/Yes'

    # 填寫 PDF
    writer.update_page_form_field_values(
        writer.pages[0],
        pdf_data,
        auto_regenerate=True
    )

    # 將結果寫入記憶體串流，而非實體檔案
    output_stream = io.BytesIO()
    writer.write(output_stream)
    output_stream.seek(0)

    # 使用 StreamingResponse 直接回傳記憶體中的 PDF
    return StreamingResponse(
        output_stream,
        media_type='application/pdf',
        headers={"Content-Disposition": 'attachment; filename="counsel_record_filled.pdf"'}
    )

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """直接回傳前端 HTML 頁面"""
    with open("counsel_form.html", "r", encoding="utf-8") as f:
        return f.read()
