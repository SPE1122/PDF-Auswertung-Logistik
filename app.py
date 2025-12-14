import io
import re
import pdfplumber
import pandas as pd
import streamlit as st


# -------- Hilfsfunktion: eine Tabellenzeile aus dem PDF parsen --------
def parse_row(line: str):
    """
    Erwartet eine Zeile wie z.B.:
    '4 L 1 10 264.541 510.330 0.000 0.000 170 2152 5852'
    und gibt eine Liste von bis zu 4 Tupeln (Bauteil, Gewicht) zurück.
    """
    tokens = line.split()
    if len(tokens) < 5:
        return []

    # Erste beiden Tokens sind Zeilennummer + L/R
    main_tokens = tokens[2:]

    # Letzte 7 Tokens: 4 Gewichte + Höhe + Breite + Länge
    weights = list(map(float, main_tokens[-7:-3]))
    element_tokens = main_tokens[:-7]

    elements = []
    i = 0
    while i < len(element_tokens) and len(elements) < 4:
        tok = element_tokens[i]
        if tok == ".":
            elements.append(None)
            i += 1
        elif tok == "Einlage" and i + 1 < len(element_tokens):
            elements.append(f"{tok} {element_tokens[i + 1]}")
            i += 2
        else:
            elements.append(tok)
            i += 1

    while len(elements) < 4:
        elements.append(None)

    return list(zip(elements, weights))


# -------- PDF komplett auslesen --------
def extract_data_from_pdf(pdf_bytes: bytes):
    """
    Gibt zurück:
      - df: alle Bauteile inkl. Einlagen
      - pritsche_ids: z.B. ['PB1','PB2',...]
      - pritschenarten: z.B. ['PB','PW',...]
      - einlage_typen: z.B. ['Einlage 80','Einlage 30',...]
    """
    records = []
    einlage_typen = set()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            # Pritsche ermitteln (z.B. "PB 1", "PB 2", "PB6 Haus A2 Vordach")
            m = re.search(r"Pritsche:\s*(.+?)\s+Unternehmer", text)
            if not m:
                continue
            pritsche_full = m.group(1).strip()

            # Buchstaben + Zahl (PB 1, PB6, PW 3, ...)
            m2 = re.search(r"([A-ZÄÖÜ]+ *\d+)", pritsche_full)
            if m2:
                pritsche_core_raw = m2.group(1)
            else:
                pritsche_core_raw = pritsche_full.split()[0]

            # PB 1 -> PB1
            pritsche_id = re.sub(r"\s+", "", pritsche_core_raw)

            # Pritschenart / Prefix (PB, PW, ...)
            m3 = re.match(r"([A-ZÄÖÜ]+)", pritsche_id)
            pritschenart = m3.group(1) if m3 else pritsche_id

            # Tabellenzeilen parsen
            for line in text.splitlines():
                if not re.match(r"[1-7]\s+[LR]\b", line):
                    continue

                pairs = parse_row(line)
                for bauteil, gewicht in pairs:
                    if not bauteil or bauteil == ".":
                        continue

                    ist_einlage = isinstance(bauteil, str) and bauteil.startswith("Einlage ")
                    einlage_typ = bauteil if ist_einlage else None
                    if ist_einlage:
                        einlage_typen.add(einlage_typ)

                    records.append(
                        {
                            "Bauteile": bauteil,
                            "PB": pritsche_id,
                            "Pritschenart": pritschenart,
                            "Gewicht [kg]": gewicht,
                            "Seite": page_index,
                            "Ist_Einlage": ist_einlage,
                            "EinlageTyp": einlage_typ,
                        }
                    )

    df = pd.DataFrame(records)
    pritsche_ids = sorted(df["PB"].unique())
    pritschenarten = sorted(df["Pritschenart"].unique())
    einlage_typen = sorted(einlage_typen)

    return df, pritsche_ids, pritschenarten, einlage_typen


# -------- Streamlit UI --------
st.set_page_config(page_title="PDF Auswertung Logistik", layout="wide")
st.title("📦 PDF Auswertung Logistik")

uploaded_file = st.file_uploader("PDF-Verladeplan hochladen", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()

    with st.spinner("PDF wird analysiert..."):
        df_all, pritsche_ids, pritschenarten, einlage_typen = extract_data_from_pdf(pdf_bytes)

    st.success("PDF erfolgreich eingelesen.")

    st.subheader("Einstellungen")

    # 1) Pritschenart auswählen (PB, PW, ...)
    selected_pritschenarten = st.multiselect(
        "Pritschen-Bezeichnungen (Prefix) auswählen",
        options=pritschenarten,
        default=pritschenarten,
        help="Es werden alle Pritschen berücksichtigt, deren Name mit diesem Prefix beginnt (z.B. PB → PB1, PB2 ...).",
    )

    # 2) Einlagen, die ignoriert werden sollen
    selected_einlagen = st.multiselect(
        "Einlagen, die NICHT ausgewertet werden sollen",
        options=einlage_typen,
        default=einlage_typen,  # Standard: Einlagen wie 'Einlage 80' werden ausgeschlossen
        help="Alle hier ausgewählten Einlagen werden aus der Bauteil-Liste entfernt.",
    )

    if st.button("🔍 Auswertung starten und Excel erzeugen"):
        if not selected_pritschenarten:
            st.error("Bitte mindestens eine Pritschen-Bezeichnung auswählen.")
        else:
            # Filtern nach Pritschenart
            df_filtered = df_all[df_all["Pritschenart"].isin(selected_pritschenarten)].copy()

            # Einlagen ggf. rausfiltern
            mask_ignorieren = df_filtered["Ist_Einlage"] & df_filtered["EinlageTyp"].isin(selected_einlagen)
            df_bauteile = df_filtered[~mask_ignorieren].copy()

            # Nur relevante Spalten für die Bauteil-Liste
            bauteile_export = df_bauteile[["Bauteiles", "PB", "Gewicht [kg]"]] if "Bauteiles" in df_bauteile.columns else df_bauteile[["Bauteile", "PB", "Gewicht [kg]"]]

            # Zusammenfassung pro Pritsche
            summary = (
                bauteile_export.groupby("PB")
                .agg(
                    Anzahl_Elemente=("Bauteile", "count"),
                    Gesamtgewicht_kg=("Gewicht [kg]", "sum"),
                )
                .reset_index()
            )

            # Gesamtzeile
            gesamt = pd.DataFrame(
                {
                    "PB": ["Gesamt"],
                    "Anzahl_Elemente": [summary["Anzahl_Elemente"].sum()],
                    "Gesamtgewicht_kg": [summary["Gesamtgewicht_kg"].sum()],
                }
            )
            summary_gesamt = pd.concat([summary, gesamt], ignore_index=True)

            # Ergebnis kurz anzeigen
            st.subheader("Vorschau: Bauteile")
            st.dataframe(bauteile_export.head(20))

            st.subheader("Vorschau: Zusammenfassung")
            st.dataframe(summary_gesamt)

            # Excel zum Download erzeugen
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                bauteile_export.to_excel(writer, index=False, sheet_name="Bauteile")
                summary_gesamt.to_excel(writer, index=False, sheet_name="Summary")

            output.seek(0)
            st.download_button(
                label="📥 Excel herunterladen",
                data=output,
                file_name="PDF_Auswertung_Logistik.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
else:
    st.info("Bitte zuerst eine PDF-Datei hochladen.")


