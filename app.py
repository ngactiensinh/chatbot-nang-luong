import streamlit as st
import os
import sys
import io
import re
import unicodedata
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from PIL import Image
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from supabase import create_client, Client

# Ép hệ thống sử dụng chuẩn UTF-8 để không bị lỗi dấu tiếng Việt
os.environ["PYTHONIOENCODING"] = "utf-8"

# --- 1. CẤU HÌNH API KEY (LẤY TỪ KÉT SẮT BẢO MẬT) ---
os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

# ==========================================
# CẤU HÌNH SUPABASE (dùng chung project với app "Theo dõi nâng lương")
# ==========================================
SUPABASE_URL = "https://qqzsdxhqrdfvxnlurnyb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFxenNkeGhxcmRmdnhubHVybnliIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MjY0NjAsImV4cCI6MjA5MTIwMjQ2MH0.H62F5zYEZ5l47fS4IdAE2JdRdI7inXQqWG0nvXhn2P8"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    pass

def log_access(app_name):
    key_name = f"da_dem_truy_cap_{app_name}"
    if key_name not in st.session_state:
        try:
            supabase.table("thong_ke_truy_cap").insert({"ten_app": app_name}).execute()
            st.session_state[key_name] = True
        except:
            pass

log_access("AI Tra cứu Lương")


# ==========================================
# MỚI: TÍNH TOÁN DIỄN BIẾN NÂNG LƯƠNG
# (Copy y hệt logic từ app "Theo dõi nâng lương" để đảm bảo 2 nơi luôn khớp nhau)
# ==========================================
def format_ma_ngach(val):
    if pd.isna(val) or val == "" or str(val).lower() == "nan":
        return ""
    val_str = str(val).strip()
    return val_str[:-2] if val_str.endswith(".0") else val_str

def tinh_toan_nang_luong(df):
    res = df.copy()
    if res.empty:
        return res
    today = datetime.now().date()
    for idx, row in res.iterrows():
        ngach    = str(row.get('ngach_luong', '')).strip().upper()
        chuc_vu  = str(row.get('chuc_vu', '')).strip().upper()
        bac_ht   = str(row.get('bac_luong', '')).strip()
        hs_str   = str(row.get('he_so_hien_tai', '0')).replace(',', '.')
        try:
            hs_ht = float(hs_str)
        except:
            hs_ht = 0.0
        vk_ht        = str(row.get('vuot_khung_hien_tai', 'None')).strip()
        ngay_ht_str  = str(row.get('ngay_gan_nhat', ''))
        try:
            ngay_ht = datetime.strptime(ngay_ht_str, '%d/%m/%Y').date()
        except:
            for col in ['bac_luong_moi', 'he_so_moi', 'vuot_khung_moi', 'ngay_du_kien']:
                res.at[idx, col] = ""
            res.at[idx, 'trang_thai'] = "Chưa có ngày"
            continue

        is_vk  = (vk_ht.lower() != 'none' and '%' in vk_ht)
        bac_moi, hs_moi, vk_moi, ngay_dk = bac_ht, hs_ht, vk_ht, ngay_ht

        if is_vk:
            vk_val  = int(vk_ht.replace('%', '').strip())
            ngay_dk = ngay_ht + relativedelta(years=1)
            vk_moi  = f"{vk_val + 1}%"
        else:
            try:
                if '/' in bac_ht:
                    x, y = map(int, bac_ht.split('/'))
                else:
                    x, y = int(bac_ht), 99
                if x >= y:
                    ngay_dk = ngay_ht + relativedelta(years=3)
                    vk_moi  = "5%"
                else:
                    bac_moi  = f"{x+1}/{y}"
                    interval = 2 if any(k in ngach or k in chuc_vu for k in
                                        ['KẾ TOÁN VIÊN TRUNG CẤP', 'LÁI XE', 'PHỤC VỤ', 'VĂN THƯ']) else 3
                    delta    = 0.34 if 'CVC' in ngach else (0.62 if 'CVCC' in ngach else 0.33)
                    ngay_dk  = ngay_ht + relativedelta(years=interval)
                    hs_moi   = hs_ht + delta
            except:
                pass

        res.at[idx, 'bac_luong_moi']  = bac_moi
        res.at[idx, 'he_so_moi']      = f"{hs_moi:.2f}".replace('.', ',')
        res.at[idx, 'vuot_khung_moi'] = vk_moi
        res.at[idx, 'ngay_du_kien']   = ngay_dk.strftime('%d/%m/%Y')

        days_left = (ngay_dk - today).days
        if days_left < 0:
            res.at[idx, 'trang_thai'] = "⛔ Đã quá hạn"
        elif days_left <= 30:
            res.at[idx, 'trang_thai'] = "🔴 Sắp đến hạn (Tháng này)"
        elif days_left <= 90:
            res.at[idx, 'trang_thai'] = "🟡 Sắp đến hạn (Quý này)"
        else:
            res.at[idx, 'trang_thai'] = "🟢 Chưa đến hạn"
    return res.fillna("")


@st.cache_data(ttl=60, show_spinner=False)
def nap_du_lieu_luong_tu_supabase():
    """Lấy dữ liệu bảng theo_doi_luong trực tiếp từ Supabase, làm mới mỗi 60 giây.
    Đây chính là bảng mà app 'Theo dõi nâng lương' ghi/sửa."""
    try:
        res = supabase.table("theo_doi_luong").select("*").execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if df.empty:
            return pd.DataFrame()
        df = tinh_toan_nang_luong(df)
        df = df[df['ho_ten'].astype(str).str.strip() != ""]
        df['ma_ngach'] = df['ma_ngach'].apply(format_ma_ngach)
        return df
    except Exception as e:
        st.warning(f"⚠️ Không lấy được dữ liệu lương từ Supabase: {e}")
        return pd.DataFrame()


def bo_dau(s):
    """Bỏ dấu tiếng Việt + chuyển thường, để 'Tuấn', 'TUẤN', 'tuan' đều so khớp được với nhau."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize('NFD', s)
    s = re.sub(r'[\u0300-\u036f]', '', s)
    s = s.replace('đ', 'd').replace('Đ', 'D')
    return s.lower().strip()


def tim_ho_so_theo_ten(df, ten_nhap):
    """Tìm hồ sơ theo tên: ưu tiên khớp chính xác, sau đó khớp chứa - không phân biệt hoa/thường và có/không dấu."""
    if df.empty:
        return pd.DataFrame()
    ten_norm = bo_dau(ten_nhap)
    if not ten_norm:
        return pd.DataFrame()
    df = df.copy()
    df['_ten_bo_dau'] = df['ho_ten'].astype(str).apply(bo_dau)
    match = df[df['_ten_bo_dau'] == ten_norm]
    if match.empty:
        match = df[df['_ten_bo_dau'].str.contains(ten_norm, na=False, regex=False)]
    return match.drop(columns=['_ten_bo_dau'], errors='ignore')


def dinh_dang_ho_so(row):
    """Trình bày đầy đủ tất cả thông tin của 1 cán bộ, lấy trực tiếp từ dữ liệu Supabase mới nhất."""
    hs_ht = str(row.get('he_so_hien_tai', ''))
    if str(row.get('vuot_khung_hien_tai', '')) not in ['', 'None', 'nan']:
        hs_ht += f" (Vượt khung {row.get('vuot_khung_hien_tai')})"
    hs_moi = str(row.get('he_so_moi', ''))
    if str(row.get('vuot_khung_moi', '')) not in ['', 'None', 'nan']:
        hs_moi += f" (Vượt khung {row.get('vuot_khung_moi')})"

    return f"""**👤 {row.get('ho_ten','')}**
- Chức vụ: {row.get('chuc_vu','') or 'Chưa cập nhật'}
- Mã ngạch: {row.get('ma_ngach','') or 'Chưa cập nhật'}
- Ngạch lương: {row.get('ngach_luong','') or 'Chưa cập nhật'}
- Bậc lương hiện tại: {row.get('bac_luong','') or 'Chưa cập nhật'}
- Hệ số hiện tại: {hs_ht or 'Chưa cập nhật'}
- Ngày hưởng lương gần nhất: {row.get('ngay_gan_nhat','') or 'Chưa cập nhật'}
- Bậc lương dự kiến tiếp theo: {row.get('bac_luong_moi','') or 'Chưa có'}
- Hệ số dự kiến: {hs_moi or 'Chưa có'}
- Ngày dự kiến nâng lương tiếp theo: {row.get('ngay_du_kien','') or 'Chưa có'}
- Trạng thái: {row.get('trang_thai','') or 'Chưa có'}

*(Dữ liệu lấy trực tiếp, tự động cập nhật từ hệ thống Theo dõi nâng lương)*"""


# ==========================================
# MỚI: TÍCH HỢP DỮ LIỆU TỪ APP "QUẢN LÝ HỒ SƠ CBCC"
# Chỉ lấy Khen thưởng/Kỷ luật + Diễn biến lương (KHÔNG lấy thông tin cá nhân/gia đình)
# để phục vụ đánh giá điều kiện nâng lương trước thời hạn
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def nap_danh_sach_ma_cbcc():
    """Chỉ lấy id + ho_ten từ ho_so_cbcc - dùng để map tên -> mã, không lấy thông tin cá nhân khác."""
    try:
        res = supabase.table("ho_so_cbcc").select("id,ho_ten").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def tim_ma_cbcc_theo_ten(ten_day_du):
    """Map họ tên -> mã CBCC. Chỉ trả về khi khớp RÕ RÀNG (1 kết quả), tránh lấy nhầm hồ sơ người khác."""
    df = nap_danh_sach_ma_cbcc()
    if df.empty or not ten_day_du:
        return None
    ten_norm = bo_dau(ten_day_du)
    df = df.copy()
    df['_bd'] = df['ho_ten'].astype(str).apply(bo_dau)
    m = df[df['_bd'] == ten_norm]
    if len(m) == 1:
        return m.iloc[0]['id']
    return None


@st.cache_data(ttl=60, show_spinner=False)
def nap_khen_thuong_ky_luat(ma_cbcc):
    try:
        res = supabase.table("khen_thuong_ky_luat").select(
            "ngay_quyet_dinh,loai,noi_dung,quyet_dinh_so"
        ).eq("ma_cbcc", ma_cbcc).order("id").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def nap_dien_bien_luong_chi_tiet(ma_cbcc):
    try:
        res = supabase.table("dien_bien_luong").select(
            "ngay_quyet_dinh,bac_luong,he_so,quyet_dinh_so"
        ).eq("ma_cbcc", ma_cbcc).order("id").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


TU_KHOA_TRUOC_HAN = [
    "truoc thoi han", "truoc han", "nang luong som", "xet som",
    "tang luong truoc", "co du dieu kien", "du dieu kien khong",
]

def la_cau_hoi_dieu_kien_truoc_han(query):
    """Nhận diện câu hỏi kiểu 'có được xét nâng lương trước thời hạn không'."""
    q = bo_dau(query)
    return any(tk in q for tk in TU_KHOA_TRUOC_HAN)


TEMPLATE_DIEU_KIEN_TRUOC_HAN = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo và Dân vận Tỉnh ủy Tuyên Quang.
Nhiệm vụ: đánh giá cán bộ có đủ điều kiện được xét nâng bậc lương trước thời hạn hay không, CHỈ dựa vào dữ liệu và quy định dưới đây. Không suy diễn hay bịa thêm điều kiện không có trong quy định.

1. THÔNG TIN LƯƠNG HIỆN TẠI CỦA CÁN BỘ:
{ho_so_luong}

2. LỊCH SỬ KHEN THƯỞNG / KỶ LUẬT:
{khen_thuong}

3. DIỄN BIẾN LƯƠNG CHI TIẾT (LỊCH SỬ CÁC LẦN NÂNG LƯƠNG):
{dien_bien_luong}

4. QUY ĐỊNH LIÊN QUAN ĐẾN NÂNG LƯƠNG TRƯỚC THỜI HẠN:
{quy_dinh}

YÊU CẦU TRẢ LỜI:
- Kết luận rõ ràng: CÓ, KHÔNG, hay "Chưa đủ căn cứ để kết luận" (nếu thiếu dữ liệu/quy định).
- Nêu căn cứ cụ thể dựa trên thành tích khen thưởng, thời gian giữ bậc lương hiện tại và quy định.
- Nếu có kỷ luật trong thời gian xét, nêu rõ ảnh hưởng đến điều kiện xét (nếu quy định có đề cập).
- Nếu đủ điều kiện, hướng dẫn ngắn gọn các bước/hồ sơ cần chuẩn bị theo đúng quy định đã cung cấp.
- Nếu tài liệu quy định không đủ thông tin để kết luận, nói rõ cần bổ sung văn bản/dữ liệu nào.

Câu hỏi của cán bộ: {question}
"""


# --- 2. THIẾT KẾ GIAO DIỆN (UI/UX) ---
try:
    page_icon_image = Image.open("Logo TGDV.png")
    st.set_page_config(page_title="Trợ lý AI - Ban TG&DV Tuyên Quang", page_icon=page_icon_image, layout="centered")
except Exception as e:
    st.set_page_config(page_title="Trợ lý AI - Ban TG&DV Tuyên Quang", page_icon="🌟", layout="centered")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .main-title {
        font-size: 28px;
        font-weight: 900;
        color: #C8102E;
        text-align: left;
        margin-bottom: 5px;
        margin-top: 15px;
        text-transform: uppercase;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    .sub-title {
        font-size: 16px;
        font-weight: 600;
        color: #004B87;
        text-align: left;
        margin-bottom: 20px;
        text-transform: uppercase;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    .divider {
        border-bottom: 2px solid #E0E0E0;
        margin-bottom: 30px;
    }

    @media (max-width: 768px) {
        .main-title { font-size: 22px; margin-top: 5px; }
        .sub-title { font-size: 14px; }
    }
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 8])
with col1:
    try:
        st.image("Logo TGDV.png", width=100)
    except Exception as e:
        st.error("Chưa tìm thấy Logo")

with col2:
    st.markdown('<div class="main-title">TRỢ LÝ AI - GIẢI ĐÁP CHẾ ĐỘ NÂNG LƯƠNG</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">BAN TUYÊN GIÁO VÀ DÂN VẬN TỈNH ỦY TUYÊN QUANG</div>', unsafe_allow_html=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# --- 3. HÀM ĐỌC VÀ TIÊU HÓA TÀI LIỆU QUY ĐỊNH (giữ nguyên - chỉ dùng cho văn bản quy định, KHÔNG còn chứa dữ liệu cá nhân) ---
@st.cache_resource
def nap_tai_lieu():
    docs = []
    folder_path = "Tai_lieu"

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        return None

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)

        if file.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
            docs.extend(loader.load())

        elif file.endswith('.docx'):
            loader = Docx2txtLoader(file_path)
            loaded_docs = loader.load()
            for doc in loaded_docs:
                doc.page_content = doc.page_content.encode('utf-8', 'ignore').decode('utf-8')
            docs.extend(loaded_docs)

        elif file.endswith('.csv'):
            loader = CSVLoader(file_path=file_path, encoding='utf-8')
            docs.extend(loader.load())

    if not docs:
        return None

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)

    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vectorstore = FAISS.from_documents(documents=splits, embedding=embeddings)
    return vectorstore

with st.spinner("Đang đồng bộ cơ sở dữ liệu quy định..."):
    try:
        vectorstore = nap_tai_lieu()
    except Exception as e:
        st.error(f"❌ Có lỗi khi đọc file tài liệu: {e}. Vui lòng kiểm tra lại định dạng file.")
        vectorstore = None

# Tải dữ liệu lương từ Supabase (luôn mới, không cần file CSV thủ công nữa)
df_luong = nap_du_lieu_luong_tu_supabase()

if vectorstore is None and df_luong.empty:
    st.info("💡 Hệ thống đã sẵn sàng. Vui lòng đưa văn bản quy định vào thư mục 'Tai_lieu' và/hoặc kiểm tra dữ liệu bảng theo_doi_luong trên Supabase.")
else:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    if vectorstore is not None:
        retriever = vectorstore.as_retriever(search_kwargs={"k": 15})

        template = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo và Dân vận Tỉnh ủy Tuyên Quang.
        Hãy chỉ sử dụng các quy định trong tài liệu được cung cấp dưới đây để trả lời câu hỏi về QUY TRÌNH, QUY ĐỊNH nâng lương.

        LƯU Ý:
        1. TUYỆT ĐỐI KHÔNG tự suy diễn dài dòng khi người dùng chỉ hỏi về quy định chung.
        2. Nếu có sự khác biệt giữa quy định chung và quy định riêng, PHẢI ƯU TIÊN áp dụng các tiêu chuẩn chi tiết tại Quy chế, Quyết định của địa phương.
        3. Nếu tài liệu không có thông tin, hãy nói 'Tôi chưa tìm thấy thông tin này', không được tự bịa ra.

        Tài liệu quy định:
        {context}

        Câu hỏi của đồng chí: {question}
        """

        prompt = ChatPromptTemplate.from_template(template)

        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        rag_chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )
    else:
        retriever = None
        rag_chain = None

    # --- 5. KHUNG CHAT TƯƠNG TÁC ---
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "goi_y_ten" not in st.session_state:
        st.session_state.goi_y_ten = []   # danh sách tên đang gợi ý để bấm nhanh
    if "cau_hoi_cho_xu_ly" not in st.session_state:
        st.session_state.cau_hoi_cho_xu_ly = None
    if "nguoi_hien_tai" not in st.session_state:
        st.session_state.nguoi_hien_tai = None

    def xu_ly_cau_hoi(user_query):
        """Xử lý 1 câu hỏi:
        0) Nếu hỏi về điều kiện nâng lương trước thời hạn -> tổng hợp dữ liệu lương + khen thưởng/kỷ luật + quy định, để LLM đánh giá.
        1) Nếu là tên người -> tra cứu trực tiếp từ Supabase.
        2) Còn lại -> hỏi RAG (quy định chung)."""
        ho_so = tim_ho_so_theo_ten(df_luong, user_query)
        goi_y_moi = []

        # NHÁNH 0: câu hỏi về điều kiện nâng lương trước thời hạn
        if la_cau_hoi_dieu_kien_truoc_han(user_query):
            doi_tuong = None
            if not ho_so.empty and len(ho_so) == 1:
                doi_tuong = ho_so.iloc[0]
            elif st.session_state.get("nguoi_hien_tai"):
                ho_so_truoc = tim_ho_so_theo_ten(df_luong, st.session_state["nguoi_hien_tai"])
                if len(ho_so_truoc) == 1:
                    doi_tuong = ho_so_truoc.iloc[0]

            if doi_tuong is None:
                answer = (
                    "Để đánh giá điều kiện nâng lương trước thời hạn, vui lòng cho tôi biết "
                    "họ và tên đầy đủ của đồng chí cần tra cứu trước nhé."
                )
                return answer, []

            ten_day_du = doi_tuong.get('ho_ten', '')
            ma_cbcc = tim_ma_cbcc_theo_ten(ten_day_du)
            kt_kl = nap_khen_thuong_ky_luat(ma_cbcc) if ma_cbcc else pd.DataFrame()
            dbl = nap_dien_bien_luong_chi_tiet(ma_cbcc) if ma_cbcc else pd.DataFrame()

            khen_thuong_text = "\n".join(
                f"- {r.get('ngay_quyet_dinh','')}: {r.get('loai','')} - {r.get('noi_dung','')} (QĐ số {r.get('quyet_dinh_so','')})"
                for _, r in kt_kl.iterrows()
            ) or "Không có dữ liệu khen thưởng/kỷ luật trong hệ thống Hồ sơ CBCC."

            dien_bien_text = "\n".join(
                f"- {r.get('ngay_quyet_dinh','')}: Bậc {r.get('bac_luong','')}, hệ số {r.get('he_so','')} (QĐ số {r.get('quyet_dinh_so','')})"
                for _, r in dbl.iterrows()
            ) or "Không có dữ liệu diễn biến lương chi tiết trong hệ thống Hồ sơ CBCC."

            quy_dinh_text = ""
            if retriever is not None:
                try:
                    docs_lq = retriever.invoke(user_query)
                    quy_dinh_text = "\n\n".join(d.page_content for d in docs_lq)
                except Exception:
                    quy_dinh_text = ""
            if not quy_dinh_text:
                quy_dinh_text = "Chưa có văn bản quy định liên quan trong thư mục Tai_lieu."

            prompt_dk = ChatPromptTemplate.from_template(TEMPLATE_DIEU_KIEN_TRUOC_HAN)
            chain_dk = prompt_dk | llm | StrOutputParser()
            answer = chain_dk.invoke({
                "ho_so_luong": dinh_dang_ho_so(doi_tuong),
                "khen_thuong": khen_thuong_text,
                "dien_bien_luong": dien_bien_text,
                "quy_dinh": quy_dinh_text,
                "question": user_query,
            })
            st.session_state["nguoi_hien_tai"] = ten_day_du
            return answer, []

        # NHÁNH 1: tra tên trực tiếp
        if not ho_so.empty and len(user_query.split()) <= 6:
            if len(ho_so) == 1:
                st.session_state["nguoi_hien_tai"] = ho_so.iloc[0].get('ho_ten', '')
                answer = dinh_dang_ho_so(ho_so.iloc[0])
            else:
                # Nhiều người trùng/gần giống tên -> gợi ý để người dùng chọn đúng, không dump hết
                goi_y = "\n".join(
                    f"- **{r.get('ho_ten','')}** ({r.get('chuc_vu','') or 'chưa rõ chức vụ'})"
                    for _, r in ho_so.iterrows()
                )
                answer = (
                    f"Tìm thấy {len(ho_so)} người có tên gần giống '{user_query}'. "
                    f"Bạn có phải muốn tìm (bấm vào tên bên dưới để xem ngay):\n\n{goi_y}"
                )
                goi_y_moi = ho_so['ho_ten'].astype(str).tolist()
        elif rag_chain is not None:
            answer = rag_chain.invoke(user_query)
        else:
            answer = "Tôi chưa tìm thấy thông tin này. Vui lòng thử nhập chính xác họ tên hoặc liên hệ quản trị viên."

        return answer, goi_y_moi

    # Hiển thị lịch sử chat
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Nút bấm nhanh cho các tên đang được gợi ý (chỉ hiện sau câu trả lời gợi ý gần nhất)
    if st.session_state.goi_y_ten:
        st.markdown("**👉 Chọn nhanh:**")
        so_cot = min(3, len(st.session_state.goi_y_ten))
        cols = st.columns(so_cot)
        for i, ten in enumerate(st.session_state.goi_y_ten):
            if cols[i % so_cot].button(ten, key=f"goiy_btn_{i}_{ten}", use_container_width=True):
                st.session_state.cau_hoi_cho_xu_ly = ten
                st.session_state.goi_y_ten = []
                st.rerun()

    # Ô nhập chat bình thường
    user_query_go = st.chat_input("Nhập tên đồng chí hoặc câu hỏi về chế độ nâng lương tại đây...")

    # Ưu tiên xử lý câu hỏi từ nút bấm (nếu có), sau đó mới đến ô gõ tay
    user_query = st.session_state.pop("cau_hoi_cho_xu_ly", None) or user_query_go

    if user_query:
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("⏳ Chuyên viên AI đang tra cứu hồ sơ...")
            try:
                answer, goi_y_moi = xu_ly_cau_hoi(user_query)
                message_placeholder.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.session_state.goi_y_ten = goi_y_moi
                if goi_y_moi:
                    st.rerun()   # rerun để hiện ngay các nút chọn nhanh bên dưới
            except Exception as e:
                message_placeholder.markdown(f"❌ Có lỗi kết nối trong quá trình xử lý: {e}")
