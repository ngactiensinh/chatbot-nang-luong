import streamlit as st
import os
import sys
import io
from PIL import Image
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
# THÊM DÒNG NÀY ĐỂ GỌI SUPABASE VÀO TRANG:
from supabase import create_client, Client 

# Ép hệ thống sử dụng chuẩn UTF-8 để không bị lỗi dấu tiếng Việt
os.environ["PYTHONIOENCODING"] = "utf-8"

# --- 1. CẤU HÌNH API KEY (LẤY TỪ KÉT SẮT BẢO MẬT) ---
os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

# ==========================================
# THÊM MỚI: CẤU HÌNH SUPABASE & HÀM ĐẾM LƯỢT TRUY CẬP
# ==========================================
SUPABASE_URL = "https://qqzsdxhqrdfvxnlurnyb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFxenNkeGhxcmRmdnhubHVybnliIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MjY0NjAsImV4cCI6MjA5MTIwMjQ2MH0.H62F5zYEZ5l47fS4IdAE2JdRdI7inXQqWG0nvXhn2P8"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    pass

def log_access(app_name):
    # Tạo key để mỗi người vào phiên làm việc chỉ bị đếm 1 lần (chống spam)
    key_name = f"da_dem_truy_cap_{app_name}"
    if key_name not in st.session_state:
        try:
            supabase.table("thong_ke_truy_cap").insert({"ten_app": app_name}).execute()
            st.session_state[key_name] = True
        except:
            pass # Nếu lỗi mạng thì bỏ qua, không làm sập Chatbot

# KÍCH HOẠT BỘ ĐẾM CHO TRANG CHATBOT NÀY
log_access("AI Tra cứu Lương")


# --- 2. THIẾT KẾ GIAO DIỆN (UI/UX) ---
# Tải logo lên Tab trình duyệt
# (Từ đây trở xuống sếp giữ nguyên y hệt file cũ nhé) ...
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
        text-align: left; /* Đổi thành căn trái để đi kèm logo */
        margin-bottom: 5px;
        margin-top: 15px;
        text-transform: uppercase;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .sub-title {
        font-size: 16px;
        font-weight: 600;
        color: #004B87; 
        text-align: left; /* Đổi thành căn trái */
        margin-bottom: 20px;
        text-transform: uppercase;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .divider {
        border-bottom: 2px solid #E0E0E0;
        margin-bottom: 30px;
    }

    /* Thêm tính năng Responsive: Tự động thu nhỏ chữ nếu xem trên màn hình nhỏ/điện thoại */
    @media (max-width: 768px) {
        .main-title { font-size: 22px; margin-top: 5px; }
        .sub-title { font-size: 14px; }
    }
</style>
""", unsafe_allow_html=True)

# Chia cột để đặt Logo bên trái, Chữ bên phải
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

# --- 3. HÀM ĐỌC VÀ TIÊU HÓA TÀI LIỆU ---
@st.cache_resource
def nap_tai_lieu():
    docs = []
    folder_path = "Tai_lieu"

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        return None

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        
        # Chỉ lấy file .pdf, .docx và .csv
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

# Trạng thái nạp dữ liệu có bọc lỗi
with st.spinner("Đang đồng bộ cơ sở dữ liệu quy định..."):
    try:
        vectorstore = nap_tai_lieu()
    except Exception as e:
        st.error(f"❌ Có lỗi khi đọc file tài liệu: {e}. Vui lòng kiểm tra lại định dạng file.")
        vectorstore = None

if vectorstore is None:
    st.info("💡 Hệ thống đã sẵn sàng. Vui lòng đưa các văn bản quy định (file PDF, DOCX hoặc CSV) vào thư mục 'Tai_lieu'.")
else:
    # --- 4. LUỒNG SUY NGHĨ CỦA AI ---
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 15}) 

    template = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo và Dân vận Tỉnh ủy Tuyên Quang. 
    Hãy chỉ sử dụng các quy định và danh sách trong tài liệu được cung cấp dưới đây để trả lời câu hỏi.
    
    LƯU Ý CỰC KỲ QUAN TRỌNG: 
    1. Nếu người dùng chỉ nhập TÊN MỘT NGƯỜI (ví dụ: Trần Mạnh Lợi, Nguyễn Văn A...), hãy TỰ ĐỘNG HIỂU là họ muốn tra cứu thông tin cá nhân của người đó. Bạn phải trích xuất và liệt kê ĐẦY ĐỦ TẤT CẢ các cột thông tin của người đó có trong danh sách (bao gồm cả Hệ số, Bậc, % vượt khung hiện hưởng, % vượt khung mới, ghi chú...). CÓ THÔNG TIN GÌ TRONG BẢNG PHẢI HIỂN THỊ HẾT RA, KHÔNG ĐƯỢC BỎ SÓT.
    2. TUYỆT ĐỐI KHÔNG tự suy diễn dài dòng sang các quy trình làm tờ trình hay luật lệ nâng lương khi người dùng chỉ hỏi thông tin cá nhân.
    3. Nếu có sự khác biệt giữa quy định chung và quy định riêng, PHẢI ƯU TIÊN áp dụng các tiêu chuẩn chi tiết tại Quy chế, Quyết định của địa phương.
    4. Nếu tài liệu không có thông tin, hãy nói 'Tôi chưa tìm thấy thông tin này', không được tự bịa ra.

    Tài liệu quy định và danh sách:
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

    # --- 5. KHUNG CHAT TƯƠNG TÁC ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_query := st.chat_input("Nhập câu hỏi về chế độ nâng lương của đồng chí tại đây..."):
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("⏳ Chuyên viên AI đang tra cứu hồ sơ...")
            try:
                answer = rag_chain.invoke(user_query)
                message_placeholder.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                message_placeholder.markdown(f"❌ Có lỗi kết nối trong quá trình xử lý: {e}")
