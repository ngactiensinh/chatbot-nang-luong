import streamlit as st
import os
import sys
import io
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


def tim_ho_so_theo_ten(df, ten_nhap):
    """Tìm hồ sơ theo tên: ưu tiên khớp chính xác, sau đó khớp chứa (không phân biệt hoa/thường)."""
    if df.empty:
        return pd.DataFrame()
    ten_norm = ten_nhap.strip().lower()
    match = df[df['ho_ten'].astype(str).str.strip().str.lower() == ten_norm]
    if match.empty:
        match = df[df['ho_ten'].astype(str).str.lower().str.contains(ten_norm, na=False)]
    return match


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
    if vectorstore is not None:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
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
        rag_chain = None

    # --- 5. KHUNG CHAT TƯƠNG TÁC ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_query := st.chat_input("Nhập tên đồng chí hoặc câu hỏi về chế độ nâng lương tại đây..."):
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("⏳ Chuyên viên AI đang tra cứu hồ sơ...")
            try:
                # BƯỚC 1: Thử tra cứu trực tiếp theo tên trong dữ liệu Supabase (chính xác, luôn mới nhất)
                ho_so = tim_ho_so_theo_ten(df_luong, user_query)

                if not ho_so.empty and len(user_query.split()) <= 6:
                    # Câu hỏi ngắn, trùng tên -> trả lời trực tiếp từ dữ liệu thật, không qua RAG
                    if len(ho_so) == 1:
                        answer = dinh_dang_ho_so(ho_so.iloc[0])
                    else:
                        answer = f"Tìm thấy {len(ho_so)} kết quả khớp với '{user_query}':\n\n" + \
                                  "\n\n---\n\n".join(dinh_dang_ho_so(r) for _, r in ho_so.iterrows())
                elif rag_chain is not None:
                    # BƯỚC 2: Câu hỏi về quy định/quy trình -> dùng RAG như cũ
                    answer = rag_chain.invoke(user_query)
                else:
                    answer = "Tôi chưa tìm thấy thông tin này. Vui lòng thử nhập chính xác họ tên hoặc liên hệ quản trị viên."

                message_placeholder.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                message_placeholder.markdown(f"❌ Có lỗi kết nối trong quá trình xử lý: {e}")
