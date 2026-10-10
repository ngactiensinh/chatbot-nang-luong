# -*- coding: utf-8 -*-
"""
TRỢ LÝ AI — GIẢI ĐÁP CHẾ ĐỘ NÂNG LƯƠNG (Ban Tuyên giáo Tỉnh ủy Tuyên Quang)
Phiên bản 2.0 — nối với app Hồ sơ CBCC mới (GitHub Pages + Supabase Auth)

- Ai cũng hỏi được quy định chung (tài liệu trong thư mục Tai_lieu).
- Tra cứu cá nhân phải đăng nhập bằng Mã cán bộ + mật khẩu của app Hồ sơ CBCC.
  Cán bộ chỉ tra được của mình; quản trị viên tra được mọi người (do RLS của Supabase quyết định).
- Dữ liệu gửi lên Gemini đã ẩn họ tên, không gửi ngày sinh, CCCD, nội dung kỷ luật.

Secrets cần có (Streamlit Cloud → Settings → Secrets):
    GOOGLE_API_KEY    = "..."
    SUPABASE_URL      = "https://xxxx.supabase.co"      # project app Hồ sơ CBCC
    SUPABASE_ANON_KEY = "eyJ..."                         # khóa anon public, KHÔNG dùng service_role
    APP_HOSO_URL      = "https://ngactiensinh.github.io/hoso-cbcc/"   # không bắt buộc
"""
import os
import re
import time
import unicodedata
from datetime import date, datetime

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta
from PIL import Image
from supabase import create_client

os.environ["PYTHONIOENCODING"] = "utf-8"

# ==========================================
# 1. CẤU HÌNH
# ==========================================
try:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
except Exception:
    st.error("⚠️ Thiếu Secrets: cần GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY.")
    st.stop()
APP_HOSO_URL = st.secrets.get("APP_HOSO_URL", "https://ngactiensinh.github.io/hoso-cbcc/")
THOI_GIAN_LAM_MOI = 60  # giây — dữ liệu cá nhân được đọc lại sau mỗi khoảng này


@st.cache_resource
def sb_chung():
    """Client dùng chung CHỈ để ghi thống kê truy cập. Không bao giờ đăng nhập trên client này."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def ghi_truy_cap():
    if "da_dem_truy_cap" in st.session_state:
        return
    st.session_state["da_dem_truy_cap"] = True
    try:
        sb_chung().table("thong_ke_truy_cap").insert({"ten_app": "AI Tra cứu Lương"}).execute()
    except Exception:
        pass


# ==========================================
# 2. TIỆN ÍCH
# ==========================================
def bo_dau(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFD", s)
    s = re.sub(r"[̀-ͯ]", "", s)
    return s.replace("đ", "d").replace("Đ", "D").lower().strip()


def thuong(s):
    """Chữ thường, giữ dấu (dùng để phân biệt 'tôi' với 'tới')."""
    return unicodedata.normalize("NFC", str(s or "")).lower()


def doc_iso(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def ngay_vn(v):
    d = v if isinstance(v, date) else doc_iso(v)
    return d.strftime("%d/%m/%Y") if d else ""


def so_vn(v, le=2):
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        return f"{float(v):.{le}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def con_lai(d):
    if not d:
        return ""
    n = (d - date.today()).days
    if n < 0:
        return f"đã quá {-n} ngày"
    if n == 0:
        return "đúng hôm nay"
    if n <= 31:
        return f"còn {n} ngày"
    return f"còn khoảng {round(n / 30.4)} tháng"


TEN_NGACH = {"CVCC": "Chuyên viên cao cấp", "CVC": "Chuyên viên chính", "CV": "Chuyên viên"}


def ten_ngach(t):
    t = str(t or "").strip()
    return TEN_NGACH.get(t.upper(), t)


# ==========================================
# 3. TÍNH NÂNG LƯƠNG, NGHỈ HƯU — giống hệt app Hồ sơ CBCC
# ==========================================
BANG_HE_SO = {
    "A3": [6.20, 6.56, 6.92, 7.28, 7.64, 8.00],
    "A2": [4.40, 4.74, 5.08, 5.42, 5.76, 6.10, 6.44, 6.78],
    "A1": [2.34, 2.67, 3.00, 3.33, 3.66, 3.99, 4.32, 4.65, 4.98],
    "B": [round(1.86 + 0.20 * i, 2) for i in range(12)],
    "LAI_XE": [round(2.05 + 0.18 * i, 2) for i in range(12)],
    "PHUC_VU": [round(1.00 + 0.18 * i, 2) for i in range(12)],
}
THOI_HAN = {"A3": 3, "A2": 3, "A1": 3, "B": 2, "LAI_XE": 2, "PHUC_VU": 2}


def nhom_ngach(ngach, ma, chuc_vu):
    n = str(ngach or "").strip().upper()
    cv = str(chuc_vu or "").upper()
    m = re.sub(r"\D", "", str(ma or ""))
    if "LÁI XE" in n or "LÁI XE" in cv:
        return "LAI_XE"
    if "PHỤC VỤ" in n or "TẠP VỤ" in cv or m == "01009":
        return "PHUC_VU"
    if "TRUNG CẤP" in n or m in ("06032", "02008"):
        return "B"
    if n == "CVCC" or "CAO CẤP" in n or m == "01001":
        return "A3"
    if n == "CVC" or "CHÍNH" in n or m == "01002":
        return "A2"
    return "A1"


def tinh_nang_luong(l, chuc_vu):
    """l: dòng hs_luong_hien_huong. Trả về dict gồm mức đang hưởng và mức/ngày nâng tiếp theo."""
    bac = str(l.get("bac_luong") or "").replace(" ", "")
    try:
        hs = float(l.get("he_so")) if l.get("he_so") not in (None, "") else None
    except (TypeError, ValueError):
        hs = None
    vk = str(l.get("vuot_khung") or "").strip()
    ngay = doc_iso(l.get("ngay_huong"))
    kq = dict(ngach=l.get("ngach_luong"), ma_ngach=l.get("ma_ngach"), bac=bac or None, he_so=hs,
              vuot_khung=vk or None, ngay_huong=ngay, bac_moi=bac or None, he_so_moi=hs,
              vuot_khung_moi=None, ngay_du_kien=None, loai="thuong_xuyen", lech=None)
    nhom = nhom_ngach(l.get("ngach_luong"), l.get("ma_ngach"), chuc_vu)
    bang, han = BANG_HE_SO[nhom], THOI_HAN[nhom]
    x = y = None
    if re.fullmatch(r"\d+/\d+", bac):
        x, y = map(int, bac.split("/"))
    elif re.fullmatch(r"\d+", bac):
        x, y = int(bac), 99
    if x and hs is not None and x <= len(bang) and abs(bang[x - 1] - hs) > 0.005:
        kq["lech"] = f"bậc {bac} theo bảng lương có hệ số {so_vn(bang[x - 1])}, đang ghi {so_vn(hs)}"
    if not ngay:
        return kq
    if "%" in vk:
        kq.update(vuot_khung_moi=f"{int(re.sub(r'[^0-9]', '', vk) or 0) + 1}%", ngay_du_kien=ngay + relativedelta(years=1), loai="vuot_khung")
    elif x is not None and x >= y:
        kq.update(vuot_khung_moi="5%", ngay_du_kien=ngay + relativedelta(years=han), loai="vuot_khung")
    elif x is not None:
        hs_moi = bang[x] if x < len(bang) else round((hs or 0) + bang[-1] - bang[-2], 2)
        kq.update(bac_moi=f"{x + 1}/{y}", he_so_moi=hs_moi, ngay_du_kien=ngay + relativedelta(years=han))
    return kq


def trang_thai(d):
    if not d:
        return "Chưa có ngày hưởng"
    n = (d - date.today()).days
    return "Đã quá hạn" if n < 0 else "Đến hạn trong 30 ngày" if n <= 30 else "Đến hạn trong 90 ngày" if n <= 90 else "Chưa đến hạn"


def nghi_huu(ngay_sinh, gioi_tinh):
    """Lộ trình tuổi nghỉ hưu theo Nghị định 135/2020/NĐ-CP. Thời điểm nghỉ hưu: ngày 01 của tháng liền sau tháng đủ tuổi."""
    ns = doc_iso(ngay_sinh)
    if not ns or gioi_tinh not in ("Nam", "Nữ"):
        return None
    nam = gioi_tinh == "Nam"

    def can(Y):
        if Y <= 2020:
            return 720 if nam else 660
        return min(720 + 3 * (Y - 2020), 744) if nam else min(660 + 4 * (Y - 2020), 720)

    for Y in range(2020, 2101):
        thang_du = ns.year * 12 + (ns.month - 1) + can(Y)
        if thang_du // 12 <= Y:
            t = thang_du + 1
            return {"tuoi": can(Y), "ngay": date(t // 12, t % 12 + 1, 1)}
    return None


def chu_tuoi(thang):
    return f"{thang // 12} tuổi" + (f" {thang % 12} tháng" if thang % 12 else "")


def thang_keo_dai(hinh_thuc):
    h = bo_dau(hinh_thuc)
    if "khien trach" in h or "canh cao" in h:
        return 6
    if "giang chuc" in h or "cach chuc" in h:
        return 12
    return None


# ==========================================
# 4. ĐĂNG NHẬP — mỗi người một client riêng trong session_state
# ==========================================
def dich_loi(e):
    m = str(e)
    if "Invalid login credentials" in m:
        return "Sai mật khẩu."
    if re.search(r"JWT|expired|refresh", m, re.I):
        return "Phiên đăng nhập đã hết hạn, đồng chí đăng nhập lại."
    if re.search(r"Failed|Connect|timed out", m, re.I):
        return "Không kết nối được máy chủ, thử lại sau ít phút."
    return m


def dang_nhap(ma, mk):
    ma = ma.strip().upper()
    if not ma or not mk:
        return "Nhập đủ mã cán bộ và mật khẩu."
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    try:
        email = sb.rpc("hs_tim_email", {"p_ma": ma}).execute().data
        if not email:
            return "Không tìm thấy mã cán bộ này."
        sess = sb.auth.sign_in_with_password({"email": email, "password": mk})
        uid = sess.user.id
        tk = (sb.table("hs_tai_khoan").select("ma_cbcc, ho_ten, vai_tro, trang_thai").eq("user_id", uid).execute().data or [None])[0]
        if not tk:
            sb.auth.sign_out()
            return "Tài khoản này không thuộc hệ thống hồ sơ."
        if tk["trang_thai"] != "Hoạt động":
            sb.auth.sign_out()
            return "Tài khoản đang chờ quản trị viên phê duyệt."
    except Exception as e:
        return dich_loi(e)
    xoa_phien()
    st.session_state.update(sb=sb, uid=uid, tk=tk, admin=tk["vai_tro"] == "Admin")
    return None


def xoa_phien():
    """Xóa toàn bộ dữ liệu cá nhân khỏi phiên (kể cả lịch sử chat)."""
    for k in ("sb", "uid", "tk", "admin", "du_lieu", "chi_tiet", "nguoi_hien_tai", "goi_y_ten", "cau_hoi_cho_xu_ly"):
        st.session_state.pop(k, None)
    st.session_state["messages"] = []


def dang_xuat():
    try:
        st.session_state["sb"].auth.sign_out()
    except Exception:
        pass
    xoa_phien()


def da_dang_nhap():
    return "sb" in st.session_state


# ==========================================
# 5. ĐỌC DỮ LIỆU — bằng phiên của chính người dùng, RLS tự giới hạn phạm vi
# ==========================================
def nap_du_lieu():
    """Danh sách hồ sơ + lương hiện hưởng mà tài khoản này được xem. Lưu tạm trong phiên 60 giây."""
    tam = st.session_state.get("du_lieu")
    if tam and time.time() - tam["luc"] < THOI_GIAN_LAM_MOI:
        return tam["ds"]
    sb = st.session_state["sb"]
    hs = sb.table("hs_ho_so").select("id, ma_cbcc, ho_ten, chuc_vu, don_vi, ngay_sinh, gioi_tinh, user_id").execute().data or []
    luong = {r["ho_so_id"]: r for r in (sb.table("hs_luong_hien_huong").select("*").execute().data or [])}
    ds = []
    for h in hs:
        l = luong.get(h["id"])
        h["_luong"] = tinh_nang_luong(l, h.get("chuc_vu")) if l else None
        h["_huu"] = nghi_huu(h.get("ngay_sinh"), h.get("gioi_tinh"))
        ds.append(h)
    st.session_state["du_lieu"] = {"luc": time.time(), "ds": ds}
    st.session_state["chi_tiet"] = {}
    return ds


def nap_chi_tiet(ho_so_id):
    """Diễn biến lương + khen thưởng/kỷ luật của một hồ sơ."""
    cache = st.session_state.setdefault("chi_tiet", {})
    if ho_so_id in cache:
        return cache[ho_so_id]
    sb = st.session_state["sb"]
    dbl = sb.table("hs_luong").select("ngay_quyet_dinh, bac_luong, he_so, ngay_nang_bac_tiep_theo, quyet_dinh_so") \
        .eq("ho_so_id", ho_so_id).order("ngay_quyet_dinh").execute().data or []
    kt = sb.table("hs_khen_thuong").select("ngay_quyet_dinh, loai, noi_dung, quyet_dinh_so, he_thong, hinh_thuc, ngay_het_han") \
        .eq("ho_so_id", ho_so_id).order("ngay_quyet_dinh").execute().data or []
    cache[ho_so_id] = (dbl, kt)
    return dbl, kt


def ho_so_cua_toi(ds):
    return next((h for h in ds if h.get("user_id") == st.session_state.get("uid")), None)


# ==========================================
# 6. NHẬN DIỆN CÂU HỎI VÀ NGƯỜI ĐƯỢC HỎI
# ==========================================
TU_KHOA = {
    "truoc_han": ["truoc thoi han", "truoc han", "nang luong som", "xet som", "co du dieu kien", "du dieu kien khong"],
    "khen_thuong": ["khen thuong", "thanh tich", "danh hieu", "ky luat", "chien si", "lao dong tien tien",
                    "bang khen", "giay khen", "thi dua", "dien bien luong", "qua trinh nang luong",
                    "lich su nang luong", "lich su luong"],
    "nghi_huu": ["nghi huu", "ve huu", "huu tri", "tuoi huu"],
    "luong": ["luong", "he so", "bac", "vuot khung"],
}
TU_CHUNG = re.compile(r"quy dinh|quy trinh|thu tuc|huong dan|van ban|thong tu|nghi dinh|can cu|la gi|the nao|\bgi\b|bao lau|bao nhieu nam|tieu chuan|ho so can")
TU_VAN_BAN = re.compile(r"quy dinh|van ban|thong tu|nghi dinh")
TU_DANH_SACH = re.compile(r"\bai\b|nhung ai|danh sach|bao nhieu nguoi|nhung dong chi|cac dong chi")
TU_BAN_THAN = re.compile(r"\b(tôi|của mình|bản thân|của em|cho em)\b")


# Từ viết hoa hay gặp trong câu hỏi nhưng không phải tên người
TU_VIET_HOA_THUONG_GAP = {"ban", "dang", "nha", "nuoc", "tinh", "uy", "bo", "noi", "vu", "luat", "nghi", "dinh", "thong", "tu",
                          "quyet", "tuyen", "quang", "giao", "chinh", "phu", "trung", "uong", "hoi", "dong", "van", "phong"}


def giong_ho_ten(q):
    """2–5 tiếng, tiếng nào cũng viết hoa chữ đầu: nhiều khả năng là họ tên người."""
    tu = re.findall(r"\w+", q)
    return 2 <= len(tu) <= 5 and all(w[:1].isupper() for w in tu)


def loai_cau_hoi(q):
    qb = bo_dau(q)
    for k in ("truoc_han", "khen_thuong", "nghi_huu", "luong"):
        if any(t in qb for t in TU_KHOA[k]):
            return k
    return None


def tim_theo_ten(ds, q):
    """Khớp họ tên: trùng khớp cả tên, hoặc cụm từ 2 tiếng trở lên nằm trong họ tên."""
    qb = re.sub(r"\s+", " ", bo_dau(q))
    if not qb:
        return []
    khop = [h for h in ds if bo_dau(h["ho_ten"]) == qb]
    if khop:
        return khop
    if len(qb.split()) >= 2:
        return [h for h in ds if qb in bo_dau(h["ho_ten"])]
    return [h for h in ds if bo_dau(h["ho_ten"]).split()[-1:] == [qb]]


def tim_trong_cau(ds, q):
    """Tìm người được nhắc trong câu dài: ưu tiên họ tên đầy đủ; dự phòng tên gọi viết hoa (ví dụ 'đồng chí Tuấn')."""
    qb = f" {re.sub(r'[^a-z0-9 ]', ' ', bo_dau(q))} "
    day_du = [h for h in ds if f" {bo_dau(h['ho_ten'])} " in qb]
    if day_du:
        return day_du
    tu_viet_hoa = {bo_dau(w) for w in re.findall(r"\w+", q) if w[:1].isupper()}
    return [h for h in ds if bo_dau(h["ho_ten"]).split()[-1:] and bo_dau(h["ho_ten"]).split()[-1] in tu_viet_hoa]


# ==========================================
# 7. TRÌNH BÀY KẾT QUẢ
# ==========================================
def muc_luong(h, kt=None):
    l = h.get("_luong")
    if not l:
        return "- Lương: chưa có dữ liệu trong mục Nâng lương của app hồ sơ."
    dong = [
        f"- Ngạch: {ten_ngach(l['ngach']) or 'chưa ghi'}" + (f" (mã {l['ma_ngach']})" if l["ma_ngach"] else ""),
        f"- Đang hưởng: bậc {l['bac'] or '?'}, hệ số {so_vn(l['he_so'])}" + (f", phụ cấp vượt khung {l['vuot_khung']}" if l["vuot_khung"] else "")
        + (f", từ ngày {ngay_vn(l['ngay_huong'])}" if l["ngay_huong"] else ""),
    ]
    if l["ngay_du_kien"]:
        moi = f"phụ cấp vượt khung {l['vuot_khung_moi']}" if l["loai"] == "vuot_khung" else f"bậc {l['bac_moi']}, hệ số {so_vn(l['he_so_moi'])}"
        dong.append(f"- Nâng lương tiếp theo: {moi}, dự kiến từ ngày **{ngay_vn(l['ngay_du_kien'])}** ({con_lai(l['ngay_du_kien'])}) — {trang_thai(l['ngay_du_kien'])}")
    else:
        dong.append("- Nâng lương tiếp theo: chưa tính được vì thiếu ngày hưởng.")
    if l["lech"]:
        dong.append(f"- ⚠️ Lưu ý: {l['lech']}. Đề nghị kiểm tra lại với Văn phòng Ban.")
    if kt and l["ngay_huong"]:
        trong_ky = [k for k in kt if k["loai"] == "Kỷ luật" and doc_iso(k["ngay_quyet_dinh"])
                    and doc_iso(k["ngay_quyet_dinh"]) >= l["ngay_huong"]
                    and (not l["ngay_du_kien"] or doc_iso(k["ngay_quyet_dinh"]) <= l["ngay_du_kien"])]
        if trong_ky:
            t = max((thang_keo_dai(k.get("hinh_thuc")) or 0) for k in trong_ky)
            dong.append("- ⚠️ Có kỷ luật trong kỳ nâng lương" + (f": theo Điều 82 Luật Cán bộ, công chức, thời gian nâng lương có thể bị kéo dài {t} tháng." if t else "; Hội đồng xét nâng lương sẽ xem xét."))
    return "\n".join(dong)


def muc_nghi_huu(h):
    nh = h.get("_huu")
    if not nh:
        thieu = [x for x, v in (("ngày sinh", h.get("ngay_sinh")), ("giới tính", h.get("gioi_tinh"))) if not v]
        return f"- Nghỉ hưu: chưa tính được vì hồ sơ thiếu {' và '.join(thieu) or 'thông tin'}. Đồng chí cập nhật tại [app Hồ sơ CBCC]({APP_HOSO_URL})."
    if nh["ngay"] < date.today():
        return f"- Nghỉ hưu: đã đến tuổi nghỉ hưu từ ngày {ngay_vn(nh['ngay'])}."
    return f"- Nghỉ hưu: thời điểm dự kiến **{ngay_vn(nh['ngay'])}**, khi đủ {chu_tuoi(nh['tuoi'])} ({con_lai(nh['ngay'])}). Tính theo lộ trình Nghị định 135/2020/NĐ-CP."


def danh_sach_khen_thuong(kt):
    if not kt:
        return "Chưa có dữ liệu khen thưởng, kỷ luật."
    dong = []
    for k in kt:
        if k["loai"] == "Kỷ luật":
            ht = " ".join(x for x in (k.get("hinh_thuc"), f"({k['he_thong']})" if k.get("he_thong") else "") if x)
            con = f"; hết thời hạn {ngay_vn(k['ngay_het_han'])}" if k.get("ngay_het_han") else ""
            dong.append(f"- {ngay_vn(k['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: **Kỷ luật** {ht} — {k.get('noi_dung') or ''}{con}")
        else:
            dong.append(f"- {ngay_vn(k['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: {k.get('noi_dung') or 'Khen thưởng'}"
                        + (f" (QĐ số {k['quyet_dinh_so']})" if k.get("quyet_dinh_so") else ""))
    return "\n".join(dong)


def danh_sach_dien_bien(dbl):
    if not dbl:
        return "Chưa có dữ liệu diễn biến lương."
    return "\n".join(f"- {ngay_vn(r['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: bậc {r.get('bac_luong') or '?'}, hệ số {so_vn(r.get('he_so'))}"
                     + (f" (QĐ số {r['quyet_dinh_so']})" if r.get("quyet_dinh_so") else "") for r in dbl)


CHAN_TRANG = f"\n\n*Dữ liệu lấy trực tiếp từ [app Hồ sơ CBCC]({APP_HOSO_URL}). Nếu thấy sai, đề nghị báo Văn phòng Ban.*"


def tra_loi_ca_nhan(h, loai):
    dbl, kt = nap_chi_tiet(h["id"])
    tieu_de = f"**👤 {h['ho_ten']}** — {h.get('chuc_vu') or ''}{', ' + h['don_vi'] if h.get('don_vi') and h['don_vi'] != 'Lãnh đạo Ban' else ''}"
    if loai == "nghi_huu":
        return f"{tieu_de}\n\n{muc_nghi_huu(h)}{CHAN_TRANG}"
    if loai == "khen_thuong":
        return f"{tieu_de}\n\n**🏆 Khen thưởng, kỷ luật**\n\n{danh_sach_khen_thuong(kt)}\n\n**📈 Diễn biến lương**\n\n{danh_sach_dien_bien(dbl)}{CHAN_TRANG}"
    return f"{tieu_de}\n\n{muc_luong(h, kt)}\n{muc_nghi_huu(h)}{CHAN_TRANG}"


def tra_loi_danh_sach(ds, loai):
    """Chỉ dành cho quản trị viên: ai sắp nâng lương / sắp nghỉ hưu."""
    hn = date.today()
    if loai == "nghi_huu":
        ds2 = sorted((h for h in ds if h["_huu"] and hn <= h["_huu"]["ngay"] <= hn + relativedelta(months=12)), key=lambda h: h["_huu"]["ngay"])
        if not ds2:
            return "Không có đồng chí nào đến tuổi nghỉ hưu trong 12 tháng tới."
        return "**Đến tuổi nghỉ hưu trong 12 tháng tới:**\n\n" + "\n".join(
            f"- {h['ho_ten']} ({h.get('chuc_vu') or ''}): {ngay_vn(h['_huu']['ngay'])}" for h in ds2)
    ds2 = sorted((h for h in ds if h["_luong"] and h["_luong"]["ngay_du_kien"] and h["_luong"]["ngay_du_kien"] <= hn + relativedelta(days=90)),
                 key=lambda h: h["_luong"]["ngay_du_kien"])
    if not ds2:
        return "Không có đồng chí nào đến hạn nâng lương trong 90 ngày tới."
    return "**Đến hạn nâng lương trong 90 ngày tới (kể cả đã quá hạn):**\n\n" + "\n".join(
        f"- {h['ho_ten']} ({h.get('chuc_vu') or ''}): "
        + (f"vượt khung {h['_luong']['vuot_khung_moi']}" if h["_luong"]["loai"] == "vuot_khung" else f"lên bậc {h['_luong']['bac_moi']}, hệ số {so_vn(h['_luong']['he_so_moi'])}")
        + f" từ {ngay_vn(h['_luong']['ngay_du_kien'])} ({con_lai(h['_luong']['ngay_du_kien'])})" for h in ds2)


# ==========================================
# 8. GEMINI — tài liệu quy định (dùng chung) và đánh giá trước hạn (đã ẩn danh)
# ==========================================
@st.cache_resource
def nap_tai_lieu():
    from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, CSVLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    docs, thu_muc = [], "Tai_lieu"
    if not os.path.exists(thu_muc):
        os.makedirs(thu_muc)
        return None
    for f in os.listdir(thu_muc):
        p = os.path.join(thu_muc, f)
        if f.endswith(".pdf"):
            docs.extend(PyPDFLoader(p).load())
        elif f.endswith(".docx"):
            for d in Docx2txtLoader(p).load():
                d.page_content = d.page_content.encode("utf-8", "ignore").decode("utf-8")
                docs.append(d)
        elif f.endswith(".csv"):
            docs.extend(CSVLoader(file_path=p, encoding="utf-8").load())
    if not docs:
        return None
    splits = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200).split_documents(docs)
    return FAISS.from_documents(splits, GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001"))


@st.cache_resource
def llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)


MAU_QUY_DINH = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo Tỉnh ủy Tuyên Quang.
Hãy chỉ sử dụng các quy định trong tài liệu được cung cấp dưới đây để trả lời câu hỏi về QUY TRÌNH, QUY ĐỊNH nâng lương.

LƯU Ý:
1. TUYỆT ĐỐI KHÔNG tự suy diễn dài dòng khi người dùng chỉ hỏi về quy định chung.
2. Nếu có sự khác biệt giữa quy định chung và quy định riêng, PHẢI ƯU TIÊN áp dụng các tiêu chuẩn chi tiết tại Quy chế, Quyết định của địa phương.
3. Nếu tài liệu không có thông tin, hãy nói 'Tôi chưa tìm thấy thông tin này', không được tự bịa ra.

Tài liệu quy định:
{context}

Câu hỏi của đồng chí: {question}
"""

MAU_TRUOC_HAN = """Bạn là chuyên gia tổ chức cán bộ của Ban Tuyên giáo Tỉnh ủy Tuyên Quang.
Nhiệm vụ: đánh giá một cán bộ (gọi là "cán bộ", không nêu tên) có đủ điều kiện được xét nâng bậc lương trước thời hạn hay không, CHỈ dựa vào dữ liệu và quy định dưới đây. Không suy diễn hay bịa thêm điều kiện không có trong quy định. Hôm nay là ngày {hom_nay}.

1. LƯƠNG HIỆN HƯỞNG:
{luong}

2. KHEN THƯỞNG:
{khen_thuong}

3. KỶ LUẬT (chỉ nêu hình thức và thời gian):
{ky_luat}

4. DIỄN BIẾN LƯƠNG:
{dien_bien}

5. QUY ĐỊNH LIÊN QUAN ĐẾN NÂNG LƯƠNG TRƯỚC THỜI HẠN:
{quy_dinh}

YÊU CẦU TRẢ LỜI:
- Kết luận rõ ràng: CÓ, KHÔNG, hay "Chưa đủ căn cứ để kết luận" (nếu thiếu dữ liệu/quy định).
- Nêu căn cứ cụ thể dựa trên thành tích khen thưởng, thời gian giữ bậc lương hiện tại và quy định.
- Nếu có kỷ luật trong thời gian xét, nêu rõ ảnh hưởng đến điều kiện xét (nếu quy định có đề cập).
- Nếu đủ điều kiện, hướng dẫn ngắn gọn các bước/hồ sơ cần chuẩn bị theo đúng quy định đã cung cấp.
- Nếu tài liệu quy định không đủ thông tin để kết luận, nói rõ cần bổ sung văn bản/dữ liệu nào.

Câu hỏi: {question}
"""


def an_ten(text, ho_ten):
    """Thay họ tên (đủ và tên gọi) bằng 'cán bộ' trước khi gửi ra ngoài."""
    out = re.sub(re.escape(ho_ten), "cán bộ", str(text), flags=re.I)
    ten_goi = ho_ten.split()[-1]
    return re.sub(rf"(?<!\w){re.escape(ten_goi)}(?!\w)", "cán bộ", out)


def danh_gia_truoc_han(h, cau_hoi, vectorstore):
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    dbl, kt = nap_chi_tiet(h["id"])
    l = h.get("_luong")
    luong = "Chưa có dữ liệu." if not l else (
        f"Ngạch {ten_ngach(l['ngach'])} (mã {l['ma_ngach'] or '?'}), bậc {l['bac']}, hệ số {so_vn(l['he_so'])}"
        + (f", phụ cấp vượt khung {l['vuot_khung']}" if l["vuot_khung"] else "")
        + f", hưởng từ ngày {ngay_vn(l['ngay_huong']) or '?'}; mốc nâng lương thường xuyên tiếp theo: {ngay_vn(l['ngay_du_kien']) or 'chưa tính được'}.")
    khen = "\n".join(f"- {ngay_vn(k['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: {an_ten(k.get('noi_dung') or 'Khen thưởng', h['ho_ten'])}"
                     for k in kt if k["loai"] == "Khen thưởng") or "Không có."
    ky_luat = "\n".join(f"- {ngay_vn(k['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: {k.get('hinh_thuc') or 'kỷ luật'}"
                        + (f" ({k['he_thong']})" if k.get("he_thong") else "") + (f", hết thời hạn {ngay_vn(k['ngay_het_han'])}" if k.get("ngay_het_han") else "")
                        for k in kt if k["loai"] == "Kỷ luật") or "Không có."
    dien_bien = "\n".join(f"- {ngay_vn(r['ngay_quyet_dinh']) or 'Chưa rõ ngày'}: bậc {r.get('bac_luong') or '?'}, hệ số {so_vn(r.get('he_so'))}" for r in dbl) or "Không có."
    quy_dinh = "Chưa có văn bản quy định liên quan trong thư mục Tai_lieu."
    if vectorstore is not None:
        truy_van = f"{an_ten(cau_hoi, h['ho_ten'])}\nThành tích khen thưởng:\n{khen}\nĐiều kiện, tiêu chuẩn, hình thức khen thưởng, danh hiệu thi đua để được xét nâng bậc lương trước thời hạn"
        docs = vectorstore.as_retriever(search_kwargs={"k": 25}).invoke(truy_van)
        quy_dinh = "\n\n".join(d.page_content for d in docs) or quy_dinh
    chain = ChatPromptTemplate.from_template(MAU_TRUOC_HAN) | llm() | StrOutputParser()
    kq = chain.invoke({"hom_nay": ngay_vn(date.today()), "luong": luong, "khen_thuong": khen, "ky_luat": ky_luat,
                       "dien_bien": dien_bien, "quy_dinh": quy_dinh, "question": an_ten(cau_hoi, h["ho_ten"])})
    return f"**Đánh giá điều kiện nâng lương trước thời hạn — đồng chí {h['ho_ten']}**\n\n{kq}{CHAN_TRANG}"


def tra_loi_quy_dinh(cau_hoi, vectorstore):
    if vectorstore is None:
        return "Hệ thống chưa có văn bản quy định trong thư mục Tai_lieu, nên chưa trả lời được câu hỏi này."
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    docs = vectorstore.as_retriever(search_kwargs={"k": 15}).invoke(cau_hoi)
    chain = ChatPromptTemplate.from_template(MAU_QUY_DINH) | llm() | StrOutputParser()
    return chain.invoke({"context": "\n\n".join(d.page_content for d in docs), "question": cau_hoi})


# ==========================================
# 9. XỬ LÝ MỘT CÂU HỎI
# ==========================================
def xu_ly_cau_hoi(q, vectorstore):
    """Trả về (câu trả lời, danh sách tên gợi ý để bấm nhanh)."""
    loai = loai_cau_hoi(q)
    qb = bo_dau(q)
    hoi_chung = bool(TU_CHUNG.search(qb))
    ngan = len(q.split()) <= 6 and "?" not in q

    if not da_dang_nhap():
        ca_nhan = bool(TU_BAN_THAN.search(thuong(q))) or giong_ho_ten(q) or (loai in ("truoc_han", "khen_thuong") and not hoi_chung)
        if ca_nhan:
            return ("Để tra cứu lương, khen thưởng, kỷ luật hay thời điểm nghỉ hưu của một đồng chí cụ thể, "
                    "đồng chí vui lòng **đăng nhập** ở thanh bên trái bằng mã cán bộ và mật khẩu của app Hồ sơ CBCC."), []
        return tra_loi_quy_dinh(q, vectorstore), []

    ds = nap_du_lieu()
    admin = st.session_state["admin"]
    toi = ho_so_cua_toi(ds)

    # Quản trị viên hỏi danh sách: "ai sắp nâng lương", "những ai nghỉ hưu năm tới"
    if admin and loai in ("luong", "nghi_huu") and TU_DANH_SACH.search(qb) and not TU_VAN_BAN.search(qb):
        return tra_loi_danh_sach(ds, loai), []

    # Xác định người được hỏi
    nguoi = []
    if TU_BAN_THAN.search(thuong(q)) and toi:
        nguoi = [toi]
    elif admin:
        nguoi = tim_theo_ten(ds, q) if (ngan and not loai) or (ngan and len(q.split()) >= 2) else []
        if not nguoi and loai:
            nguoi = tim_trong_cau(ds, q)
        if not nguoi and loai and not hoi_chung and st.session_state.get("nguoi_hien_tai"):
            nguoi = [h for h in ds if h["id"] == st.session_state["nguoi_hien_tai"]]
    else:
        # Cán bộ thường: chỉ có hồ sơ của mình; câu hỏi cá nhân mặc định là về bản thân
        ten_khac = tim_theo_ten(ds, q) if ngan else []
        ten_toi = set(bo_dau(toi["ho_ten"]).split()) if toi else set()
        ten_la = [w for i, w in enumerate(re.findall(r"\w+", q)) if i > 0 and w[:1].isupper()
                  and bo_dau(w) not in ten_toi and bo_dau(w) not in TU_VIET_HOA_THUONG_GAP]
        if (not ten_khac and giong_ho_ten(q) and not hoi_chung) or (ten_la and not hoi_chung and not TU_BAN_THAN.search(thuong(q))):
            return ("Tài khoản của đồng chí chỉ tra cứu được thông tin của chính mình. "
                    "Đồng chí có thể hỏi, ví dụ: *Lương của tôi bao giờ được nâng?*"), []
        if toi and (ten_khac or (loai and not hoi_chung)):
            nguoi = [toi]

    if len(nguoi) > 1:
        goi_y = "\n".join(f"- **{h['ho_ten']}** ({h.get('chuc_vu') or 'chưa rõ chức vụ'})" for h in nguoi)
        return f"Có {len(nguoi)} đồng chí khớp với câu hỏi. Đồng chí muốn tra cứu ai (bấm tên bên dưới)?\n\n{goi_y}", [h["ho_ten"] for h in nguoi]

    if len(nguoi) == 1:
        h = nguoi[0]
        st.session_state["nguoi_hien_tai"] = h["id"]
        if loai == "truoc_han":
            return danh_gia_truoc_han(h, q, vectorstore), []
        return tra_loi_ca_nhan(h, loai), []

    if loai and not hoi_chung and admin and not st.session_state.get("nguoi_hien_tai"):
        return "Đồng chí cho biết họ và tên của người cần tra cứu nhé.", []
    return tra_loi_quy_dinh(q, vectorstore), []


# ==========================================
# 10. GIAO DIỆN
# ==========================================
try:
    st.set_page_config(page_title="Trợ lý AI - Ban Tuyên giáo Tuyên Quang", page_icon=Image.open("Logo TGDV.png"), layout="centered")
except Exception:
    st.set_page_config(page_title="Trợ lý AI - Ban Tuyên giáo Tuyên Quang", page_icon="🌟", layout="centered")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .main-title { font-size: 28px; font-weight: 900; color: #C8102E; margin: 15px 0 5px; text-transform: uppercase; font-family: 'Segoe UI', Tahoma, sans-serif; }
    .sub-title { font-size: 16px; font-weight: 600; color: #0D1B2A; margin-bottom: 20px; text-transform: uppercase; font-family: 'Segoe UI', Tahoma, sans-serif; }
    .divider { border-bottom: 2px solid #F5A623; margin-bottom: 24px; }
    .trang-thai { font-size: 14px; color: #3A4656; background: #FDF1D6; border-left: 3px solid #F5A623; padding: 8px 12px; border-radius: 4px; margin-bottom: 16px; }
    @media (max-width: 768px) { .main-title { font-size: 22px; margin-top: 5px; } .sub-title { font-size: 14px; } }
</style>
""", unsafe_allow_html=True)

ghi_truy_cap()
for k, v in (("messages", []), ("goi_y_ten", []), ("cau_hoi_cho_xu_ly", None)):
    st.session_state.setdefault(k, v)

# Thanh bên: đăng nhập / đăng xuất
with st.sidebar:
    st.markdown("### 🔐 Tra cứu cá nhân")
    if not da_dang_nhap():
        st.caption("Đăng nhập bằng mã cán bộ và mật khẩu của app Hồ sơ CBCC để tra cứu lương, khen thưởng, nghỉ hưu.")
        with st.form("dang_nhap", clear_on_submit=False):
            ma = st.text_input("Mã cán bộ", placeholder="Ví dụ: CV12")
            mk = st.text_input("Mật khẩu", type="password")
            if st.form_submit_button("Đăng nhập", use_container_width=True, type="primary"):
                with st.spinner("Đang đăng nhập..."):
                    loi = dang_nhap(ma, mk)
                if loi:
                    st.error(loi)
                else:
                    st.rerun()
        st.caption(f"Quên mật khẩu: liên hệ Văn phòng Ban. [Mở app Hồ sơ CBCC]({APP_HOSO_URL})")
    else:
        tk = st.session_state["tk"]
        st.success(f"**{tk['ho_ten']}**  \nMã {tk['ma_cbcc']} · {'quản trị viên' if st.session_state['admin'] else 'cán bộ'}")
        if st.button("Đăng xuất", use_container_width=True):
            dang_xuat()
            st.rerun()
        st.caption("Đăng xuất sẽ xóa lịch sử trò chuyện trên máy này.")

col1, col2 = st.columns([1, 8])
with col1:
    try:
        st.image("Logo TGDV.png", width=100)
    except Exception:
        pass
with col2:
    st.markdown('<div class="main-title">Trợ lý AI - Giải đáp chế độ nâng lương</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Ban Tuyên giáo Tỉnh ủy Tuyên Quang</div>', unsafe_allow_html=True)
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

if da_dang_nhap():
    if st.session_state["admin"]:
        st.markdown('<div class="trang-thai">Quản trị viên: tra cứu được mọi cán bộ. Ví dụ: <i>Nguyễn Thu Vân</i>, <i>Ai sắp nâng lương?</i>, <i>Đồng chí Tuấn có đủ điều kiện nâng lương trước thời hạn không?</i></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="trang-thai">Ví dụ: <i>Lương của tôi bao giờ được nâng?</i>, <i>Khen thưởng của tôi</i>, <i>Khi nào tôi nghỉ hưu?</i>, <i>Tôi có đủ điều kiện nâng lương trước thời hạn không?</i></div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="trang-thai">Chưa đăng nhập: hỏi được các quy định chung về nâng lương. Muốn tra cứu thông tin cá nhân, đăng nhập ở thanh bên trái (trên điện thoại bấm biểu tượng » ở góc trên).</div>', unsafe_allow_html=True)

with st.spinner("Đang đồng bộ cơ sở dữ liệu quy định..."):
    try:
        vectorstore = nap_tai_lieu()
    except Exception as e:
        st.error(f"❌ Có lỗi khi đọc tài liệu quy định: {e}")
        vectorstore = None

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if st.session_state.goi_y_ten:
    st.markdown("**👉 Chọn nhanh:**")
    so_cot = min(3, len(st.session_state.goi_y_ten))
    cols = st.columns(so_cot)
    for i, ten in enumerate(st.session_state.goi_y_ten):
        if cols[i % so_cot].button(ten, key=f"goiy_{i}_{ten}", use_container_width=True):
            st.session_state.cau_hoi_cho_xu_ly = ten
            st.session_state.goi_y_ten = []
            st.rerun()

go_tay = st.chat_input("Hỏi về quy định nâng lương, hoặc tra cứu lương, khen thưởng, nghỉ hưu...")
cau_hoi = st.session_state.pop("cau_hoi_cho_xu_ly", None) or go_tay
st.session_state.cau_hoi_cho_xu_ly = None

if cau_hoi:
    st.session_state.messages.append({"role": "user", "content": cau_hoi})
    with st.chat_message("user"):
        st.markdown(cau_hoi)
    with st.chat_message("assistant"):
        o = st.empty()
        o.markdown("⏳ Đang tra cứu...")
        try:
            tra_loi, goi_y = xu_ly_cau_hoi(cau_hoi, vectorstore)
        except Exception as e:
            loi = dich_loi(e)
            if "hết hạn" in loi:
                dang_xuat()
            tra_loi, goi_y = f"❌ {loi}", []
        o.markdown(tra_loi)
        st.session_state.messages.append({"role": "assistant", "content": tra_loi})
        st.session_state.goi_y_ten = goi_y
        if goi_y:
            st.rerun()
