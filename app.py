import streamlit as st
import os
import sys
import io
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

# Ép hệ thống sử dụng chuẩn UTF-8 để không bị lỗi dấu tiếng Việt
os.environ["PYTHONIOENCODING"] = "utf-8"

# --- 1. CẤU HÌNH API KEY (LẤY TỪ KÉT SẮT BẢO MẬT) ---
os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

# --- 2. THIẾT KẾ GIAO DIỆN (UI/UX) ---
st.set_page_config(page_title="Trợ lý AI - Ban TG&DV Tuyên Quang", page_icon="🌟", layout="centered")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .main-title {
        font-size: 28px; /* Đã giảm cỡ chữ từ 34px xuống 28px để vừa 1 dòng */
        font-weight: 900;
        color: #C8102E; 
        text-align: center;
        margin-bottom: 5px;
        text-transform: uppercase;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .sub-title {
        font-size: 16px; /* Giảm cỡ chữ phụ cho cân đối với tiêu đề chính */
        font-weight: 600;
        color: #004B87; 
        text-align: center;
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
        .main-title { font-size: 22px; }
        .sub-title { font-size: 14px; }
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🌟 TRỢ LÝ AI - GIẢI ĐÁP CHẾ ĐỘ NÂNG LƯƠNG</div>', unsafe_allow_html=True)
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
        st.error(f"❌ Có lỗi khi đọc file tài liệu: {e}. Vui lòng kiểm tra lại định dạng file (chỉ dùng .docx hoặc .pdf).")
        vectorstore = None

if vectorstore is None:
    st.info("💡 Hệ thống đã sẵn sàng. Vui lòng đưa các văn bản quy định (chỉ nhận file PDF hoặc DOCX) vào thư mục 'Tai_lieu'.")
else:
    # --- 4. LUỒNG SUY NGHĨ CỦA AI ---
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 15}) 

    template = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo và Dân vận Tỉnh ủy Tuyên Quang. Hãy chỉ sử dụng các quy định trong tài liệu được cung cấp dưới đây để trả lời câu hỏi.
    
    LƯU Ý ĐẶC BIỆT: Nếu có sự khác biệt giữa quy định chung và quy định riêng, PHẢI ƯU TIÊN áp dụng các tiêu chuẩn chi tiết tại Quy chế, Quyết định của địa phương (tỉnh Tuyên Quang) cao hơn các Thông tư chung của Bộ/Ngành.
    Nếu tài liệu không có thông tin, hãy nói rõ 'Tôi chưa tìm thấy quy định cụ thể về vấn đề này trong cơ sở dữ liệu hiện tại', tuyệt đối không tự suy diễn kiến thức bên ngoài.

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