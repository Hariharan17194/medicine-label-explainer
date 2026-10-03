"""
app.py — the website (Streamlit UI).

Run locally:   streamlit run app.py
"""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # reads .env BEFORE explainer reads the env vars

from explainer import explain_medicine, get_client, prepare_image, to_text_report  # noqa: E402

# ---------- Page setup ----------
st.set_page_config(page_title="Medicine Label Explainer", page_icon="💊", layout="centered")

LANGUAGES = ["English", "Tamil", "Hindi", "Telugu", "Malayalam", "Kannada"]


@st.cache_resource
def load_client():
    return get_client()


def show_list(title: str, items: list, icon: str = "•"):
    if items:
        st.markdown(f"**{title}**")
        for item in items:
            st.markdown(f"{icon} {item}")


# ---------- Header ----------
st.title("💊 AI Medicine Label Explainer")
st.caption("Take a photo of a medicine strip, bottle or prescription and get it explained in simple words.")

st.warning(
    "⚠️ For general information only — not medical advice. "
    "Always follow your doctor or pharmacist. In an emergency, call 108.",
)

# ---------- Inputs ----------
language = st.selectbox("Explain in", LANGUAGES)

tab_upload, tab_camera = st.tabs(["📁 Upload photo", "📷 Use camera"])
with tab_upload:
    uploaded = st.file_uploader("Medicine photo", type=["jpg", "jpeg", "png", "webp"])
with tab_camera:
    camera = st.camera_input("Take a clear photo of the label")

image_file = uploaded or camera
if image_file:
    st.image(image_file, caption="Your photo", use_container_width=True)

medicine_name = st.text_input(
    "Medicine name (optional)",
    placeholder="e.g. Dolo 650 — helps if the photo is blurry, or use it without a photo",
)

# ---------- Action ----------
if st.button("Explain this medicine", type="primary", use_container_width=True):
    if not image_file and not medicine_name.strip():
        st.error("Please upload a photo or type a medicine name.")
        st.stop()

    try:
        client = load_client()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    with st.spinner("Reading the label..."):
        try:
            image_b64 = prepare_image(image_file.getvalue()) if image_file else None
            result = explain_medicine(client, image_b64, medicine_name.strip(), language)
        except Exception as e:  # network / API errors
            st.error(f"Something went wrong: {e}")
            st.stop()

    st.session_state["result"] = result

# ---------- Results ----------
result = st.session_state.get("result")
if result:
    st.divider()
    if not result.get("readable", True):
        st.error(result.get("message") or "Could not read the label. Try a clearer photo in good light.")
    elif not result["medicines"]:
        st.error(result.get("message") or "No medicines found. Try a clearer photo in good light.")
    else:
        medicines = result["medicines"]
        doc_type = result.get("document_type") or "Your photo"
        st.header(f"{doc_type}: {len(medicines)} medicine(s) found")

        # ---- Quick overview of all medicines ----
        st.table(
            [
                {
                    "Medicine": f"{m.get('medicine_name', '')} {m.get('strength', '')}".strip(),
                    "What it is for": m.get("summary", ""),
                    "Expiry": (m.get("expiry_date", "") + (" ❌ EXPIRED" if m.get("expired") else "")).strip(),
                }
                for m in medicines
            ]
        )

        expired = [m.get("medicine_name", "") for m in medicines if m.get("expired")]
        if expired:
            st.error("❌ **Expired — do not use, ask your pharmacist:** " + ", ".join(expired))

        # ---- Full explanation of each medicine ----
        for i, med in enumerate(medicines, 1):
            name = med.get("medicine_name") or f"Medicine {i}"
            title = f"{i}. {name} {med.get('strength', '')}".strip()
            with st.expander(title, expanded=len(medicines) == 1):
                if med.get("active_ingredients"):
                    st.caption("Contains: " + ", ".join(med["active_ingredients"]))

                col1, col2 = st.columns(2)
                with col1:
                    show_list("✅ Used for", med.get("used_for", []))
                    show_list("🕒 How to take", med.get("how_to_take", []))
                with col2:
                    show_list("😐 Common side effects", med.get("common_side_effects", []))
                    show_list("⚠️ Precautions", med.get("precautions", []))

                show_list("🚫 Do not take if", med.get("do_not_take_if", []))

                if med.get("see_doctor_urgently_if"):
                    st.error("**See a doctor urgently if:**\n\n" + "\n".join(f"- {x}" for x in med["see_doctor_urgently_if"]))

                info = []
                if med.get("storage"):
                    info.append(f"📦 Storage: {med['storage']}")
                if med.get("expiry_date"):
                    info.append(f"📅 Expiry: {med['expiry_date']}" + (" — ❌ EXPIRED" if med.get("expired") else ""))
                if info:
                    st.info("  \n".join(info))

        st.download_button(
            "⬇️ Download all as text",
            data=to_text_report(result),
            file_name="medicines_explained.txt",
            mime="text/plain",
            use_container_width=True,
        )

st.divider()
st.caption("Photos are sent to the AI only to read the label and are not stored by this website.")
