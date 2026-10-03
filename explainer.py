"""
explainer.py — the "AI brain" of the app.

Two jobs:
  1. prepare_image()     -> shrink + convert the uploaded photo to base64 (cheaper, faster API calls)
  2. explain_medicine()  -> send image/text to the LLM and get back structured JSON
"""

import base64
import io
import json
import os
from datetime import date

from openai import OpenAI
from PIL import Image

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # vision-capable + cheap
MAX_SIDE = 1600  # px — big enough to read small print, small enough to be cheap

SYSTEM_PROMPT = """
You are a careful pharmacy information assistant. You explain medicine labels,
strips, prescriptions and pharmacy bills to ordinary people (often elderly) in very simple words.

Today's date is __TODAY__.

RULES (follow strictly):
1. Find EVERY medicine in the image. A bill or prescription often lists many medicines —
   add one entry to "medicines" for each one, in the order they appear. Never skip any.
   Ayurvedic / herbal products and supplements count as medicines too.
2. Read ONLY what is visible, plus well-established general information about the
   active ingredient(s). If the label shows only a brand name, use the commonly known
   active ingredient(s) of that brand.
3. NEVER invent a dose. For "how_to_take", repeat what the label / prescription says
   (e.g. "1-0-1" means morning and night). If no dose is visible, write:
   "Follow the dose your doctor prescribed."
4. If the expiry date is visible and is before today's date, set "expired" to true.
5. If the image has no medicine, or is too blurry to read, set "readable" to false,
   leave "medicines" empty, and explain what the user should do in "message".
6. Do NOT diagnose and do NOT recommend other medicines.
7. Write every text value in __LANGUAGE__. Keep medicine names, ingredient names and
   strengths (e.g. "Paracetamol 500 mg") in English.
8. Use short, simple sentences. Max 4 items per list.
9. Leave a field as "" or [] if the information is not available. Do not guess.

Return ONLY valid JSON with exactly these keys:
{
  "readable": true,
  "message": "",
  "document_type": "",            // e.g. "Pharmacy bill", "Prescription", "Tablet strip"
  "medicines": [
    {
      "medicine_name": "",
      "active_ingredients": [],
      "strength": "",
      "summary": "",              // one short sentence: what this medicine is for
      "used_for": [],
      "how_to_take": [],
      "common_side_effects": [],
      "precautions": [],
      "do_not_take_if": [],
      "see_doctor_urgently_if": [],
      "storage": "",
      "expiry_date": "",
      "expired": false
    }
  ]
}
"""


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your .env file.")
    return OpenAI(api_key=api_key)


def prepare_image(file_bytes: bytes) -> str:
    """Resize the photo and return it as a base64 JPEG string."""
    img = Image.open(io.BytesIO(file_bytes))
    img = img.convert("RGB")             # handles PNG / transparency / phone formats
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # keeps aspect ratio
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def explain_medicine(
    client: OpenAI,
    image_b64: str | None,
    medicine_name: str = "",
    language: str = "English",
) -> dict:
    """Ask the LLM to explain the medicine. Returns a Python dict."""
    system = SYSTEM_PROMPT.replace("__LANGUAGE__", language).replace("__TODAY__", date.today().isoformat())

    user_text = "Explain every medicine in this image for a patient."
    if medicine_name:
        user_text += f" The user says the medicine name is: {medicine_name}."
    if not image_b64:
        user_text += " No photo was given — use only the name above."

    content = [{"type": "text", "text": user_text}]
    if image_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "high"},
            }
        )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,  # low = more factual, less creative
        response_format={"type": "json_object"},  # forces valid JSON
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"readable": False, "message": "The AI reply could not be read. Please try again."}
    if not isinstance(data.get("medicines"), list):
        data["medicines"] = []
    return data


SECTIONS = [
    ("Active ingredients", "active_ingredients"),
    ("Used for", "used_for"),
    ("How to take", "how_to_take"),
    ("Common side effects", "common_side_effects"),
    ("Precautions", "precautions"),
    ("Do not take if", "do_not_take_if"),
    ("See a doctor urgently if", "see_doctor_urgently_if"),
]


def to_text_report(data: dict) -> str:
    """Turn the result (all medicines) into plain text so the user can download / share it."""
    medicines = data.get("medicines") or []
    lines = []
    if data.get("document_type"):
        lines.append(f"{data['document_type']} — {len(medicines)} medicine(s)")
    for i, med in enumerate(medicines, 1):
        lines.append(f"\n{'=' * 50}\n{i}. {med.get('medicine_name', '')} {med.get('strength', '')}".rstrip())
        if med.get("summary"):
            lines.append(med["summary"])
        for title, key in SECTIONS:
            items = med.get(key) or []
            if items:
                lines.append(f"\n{title}:")
                lines.extend(f"  - {item}" for item in items)
        if med.get("storage"):
            lines.append(f"\nStorage: {med['storage']}")
        if med.get("expiry_date"):
            lines.append(f"Expiry: {med['expiry_date']}" + ("  (EXPIRED — do not use)" if med.get("expired") else ""))
    lines.append("\nThis is general information only. Always follow your doctor or pharmacist.")
    return "\n".join(lines)
