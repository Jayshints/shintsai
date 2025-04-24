import streamlit as st
import pdfplumber
import mammoth
import openai
import os
import re
import json
import time

openai.api_key = "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"

# 세션 상태 초기화
for key in ['extracted_text', 'translated_text', 'styled_text', 'toxic_clauses', 'last_file']:
    if key not in st.session_state:
        st.session_state[key] = None

def extract_text_from_file(file):
    if file.type == "application/pdf":
        with pdfplumber.open(file) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        result = mammoth.extract_raw_text(file)
        return result.value
    return None

translation_cache = {}

def translate_text_batch(text, batch_size=5):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    batches = [paragraphs[i:i + batch_size] for i in range(0, len(paragraphs), batch_size)]
    total_batches = len(batches)

    st.markdown(f"#### 🔄 번역 중... 총 {len(paragraphs)}문단 ({total_batches}배치)")
    progress_bar = st.progress(0)
    status_text = st.empty()
    all_translated = []

    for batch_idx, batch in enumerate(batches):
        batch_text = "\n\n---PARAGRAPH_SEPARATOR---\n\n".join(batch)
        status_text.markdown(f"📘 번역 중: 배치 {batch_idx + 1}/{total_batches}")

        if batch_text in translation_cache:
            batch_results = translation_cache[batch_text].split("\n\n---PARAGRAPH_SEPARATOR---\n\n")
        else:
            for attempt in range(3):
                try:
                    response = openai.chat.completions.create(
                        model="gpt-4-turbo",
                        messages=[
                            {"role": "system", "content": (
                                "You are a legal translator. Translate the following English contract paragraphs into formal Korean. "
                                "Preserve paragraph breaks. Paragraphs are separated by '---PARAGRAPH_SEPARATOR---'."
                            )},
                            {"role": "user", "content": batch_text}
                        ],
                        temperature=0.3
                    )
                    translated_batch = response.choices[0].message.content.strip()
                    translation_cache[batch_text] = translated_batch
                    batch_results = translated_batch.split("\n\n---PARAGRAPH_SEPARATOR---\n\n")
                    break
                except Exception as e:
                    if attempt == 2:
                        batch_results = [f"번역 오류: {e}"] * len(batch)
                    time.sleep(2)

        all_translated.extend(batch_results)
        progress_bar.progress(min((batch_idx + 1) / total_batches, 1.0))

    return "\n\n".join(all_translated)

def emphasize_titles(text):
    return re.sub(r"(제\s?\d+\s?조(?:\s?[^\n]*))", r"**\1**", text)

def detect_toxic_clauses_batch(original_text, translated_text, batch_size=8):
    original_paragraphs = [p.strip() for p in original_text.split("\n\n") if p.strip()]
    translated_paragraphs = [p.strip() for p in translated_text.split("\n\n") if p.strip()]
    paired = [{"original": o, "translated": t} for o, t in zip(original_paragraphs, translated_paragraphs)]

    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(0, len(paired), batch_size):
        batch = paired[i:i + batch_size]
        batch_idx = i // batch_size
        status_text.markdown(f"☠️ 독소조항 감지 중... 배치 {batch_idx + 1}/{(len(paired)-1)//batch_size + 1}")

        for attempt in range(3):
            try:
                response = openai.chat.completions.create(
                    model="gpt-4-turbo",
                    messages=[
                        {"role": "system", "content": (
                            "You are a legal expert. For each contract paragraph pair, identify toxic clauses.\n\n"
                            "Return a JSON array in the following format:\n"
                            "[{\n"
                            "  \"title\": \"조항 제목\",\n"
                            "  \"original\": \"영문 조항\",\n"
                            "  \"translated\": \"한글 번역\",\n"
                            "  \"risk\": \"위험 요소 설명\",\n"
                            "  \"revision_ko\": \"위험 완화를 위한 수정 제안 (한글)\",\n"
                            "  \"revision_en\": \"수정된 영문 조항 제안\"\n"
                            "}]\n\n"
                            "If no issue is found, return an empty array [].\n"
                            "⚠️ 반드시 유효한 JSON 형식으로만 출력하세요. 그 외 설명은 포함하지 마세요."
                        )},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}
                    ],
                    temperature=0.3
                )
                response_text = response.choices[0].message.content.strip()
                response_text = re.sub(r'^```(json)?', '', response_text).strip('` \n')
                parsed = json.loads(response_text)
                if isinstance(parsed, list):
                    results.extend(parsed)
                break
            except Exception as e:
                if attempt == 2:
                    st.warning(f"⚠️ 배치 {batch_idx+1} 오류: {e}")
                time.sleep(2)

        progress_bar.progress(min((i + batch_size) / len(paired), 1.0))

    return results

# Streamlit UI
st.set_page_config(page_title="SHINTS 계약서 분석기", layout="wide")
st.title("📄 SHINTS AI 번역 + 독소조항 감지기")
st.caption("AI 기반 고도화 분석 (위험 식별 + 개선안 제시)")

with st.sidebar:
    st.header("⚙️ 설정")
    batch_size = st.slider("번역 배치 크기", 1, 10, 5)
    toxic_batch_size = st.slider("독소조항 감지 배치 크기", 1, 15, 8)

uploaded_file = st.file_uploader("📤 PDF 또는 Word 파일 업로드", type=["pdf", "docx"])

if uploaded_file:
    file_name = uploaded_file.name
    if st.session_state.last_file != file_name:
        for key in ['extracted_text', 'translated_text', 'styled_text', 'toxic_clauses']:
            st.session_state[key] = None
        st.session_state.last_file = file_name

    start = time.time()

    if not st.session_state.extracted_text:
        with st.status("📄 텍스트 추출 중...", expanded=True) as status:
            extracted = extract_text_from_file(uploaded_file)
            if not extracted:
                st.error("❌ 텍스트 추출 실패")
                st.stop()
            st.session_state.extracted_text = extracted
            status.update(label="✅ 텍스트 추출 완료", state="complete", expanded=False)

    if not st.session_state.translated_text:
        with st.status("🌐 번역 중...", expanded=True) as status:
            translated = translate_text_batch(st.session_state.extracted_text, batch_size)
            st.session_state.translated_text = translated
            st.session_state.styled_text = emphasize_titles(translated)
            status.update(label="✅ 번역 완료", state="complete", expanded=False)

    tab1, tab2 = st.tabs(["📘 전문 번역", "☠️ 독소조항 감지 및 수정안"])

    with tab1:
        st.markdown(f"""
            <div style='background-color:#f0f2f6; padding:20px; border-radius:10px; line-height:2; font-size:16px;'>
            {st.session_state.styled_text.replace("\n", "<br>")}
            </div>
        """, unsafe_allow_html=True)

        st.download_button(
            label="📥 번역문 다운로드 (TXT)",
            data=st.session_state.translated_text,
            file_name=f"{os.path.splitext(file_name)[0]}_translated.txt",
            mime="text/plain"
        )

    with tab2:
        if not st.session_state.toxic_clauses:
            with st.status("☠️ 독소조항 감지 중...", expanded=True) as status:
                st.session_state.toxic_clauses = detect_toxic_clauses_batch(
                    st.session_state.extracted_text,
                    st.session_state.translated_text,
                    toxic_batch_size
                )
                status.update(label="✅ 감지 완료", state="complete", expanded=False)

        if st.session_state.toxic_clauses:
            st.markdown(f"### ⚠️ 총 {len(st.session_state.toxic_clauses)}개 독소조항 감지됨")
            for i, clause in enumerate(st.session_state.toxic_clauses, 1):
                with st.expander(f"{i}. {clause.get('title', '제목 없음')}"):
                    st.markdown(f"""
                        **🔹 원문:**<br>{clause.get('original', '')}<br><br>
                        **📘 번역:**<br>{clause.get('translated', '')}<br><br>
                        **⚠️ 위험 요소:**<br>{clause.get('risk', '')}<br><br>
                        **🛠 위험 완화 제안 (한글):**<br>{clause.get('revision_ko', 'N/A')}<br><br>
                        **✏️ 수정된 영어 문장:**<br>{clause.get('revision_en', 'N/A')}
                    """, unsafe_allow_html=True)
        else:
            st.info("☑️ 감지된 독소조항이 없습니다.")

    st.success(f"🎉 전체 완료! 총 소요 시간: {time.time() - start:.1f}초")




