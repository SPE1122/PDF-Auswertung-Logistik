import io
import re

import pdfplumber
import pandas as pd
import streamlit as st


# ===================== Hilfsfunktionen =====================

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

    # letzte 7 Tokens: 4 Gewichte + Höhe + Breite + Länge
    if len(main_tokens) < 7:
        return []
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
            # "Einlage 80" zusammenführen
            elements.append(f"{tok} {element_tokens[i + 1]}")
            i += 2
        else:
            elements.append(tok)
            i += 1

    # ggf. auf 4 Positionen auffüllen
    while len(elements) < 4:
        elements.append(None)

    return list(zip(elements, weights))


def extract_data_from_pdf(pdf_bytes: bytes):
    """
    Liest alle Seiten und liefert:
      df: alle Bauteile inkl. Einlagen
      pritsche_ids: ['PB1', 'PB2', ...]
      pritschenarten: ['PB', 'PW', ...]
      einlage_typen: ['Einlage 80', 'Einlage 30', ...]
    """
    records = []
    einlage_typen = set()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            # Pritsche ermitteln (zwischen "Pritsche:" und "Unternehmer")
            m = re.search(r"Pritsche:\s*(.+?)\s+Unternehmer", text)
            if not m:
                continue
            pritsche_full = m.group(1).strip()

            # z.B. "PB 1", "PB 2", "PB6 Haus A2 Vordach"
            m2 = re.search(r"([A-ZÄÖÜ]+ *\d+)", pritsche_full)
            if m2:
                pritsche_core_raw = m2.group(1)
            else:
                pritsche_core_raw = pritsche_full.split()[0]

            # "PB 1" -> "PB1"
            pritsche_id = re.sub(r"\s+", "", pritsche_core_raw)

            # Prefix / Pritschenart (PB, PW, ...)
            m3 = re.match(r"([A-ZÄÖÜ]+)", pritsche_id)
            pritschenart = m3.group(1) if m3 else pritsche_id

            # Tabellenzeilen parsen (Zeilen, die mit "1 L", "3 R", ... beginnen)
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
                            "Bauteil_raw": bauteil,
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


# ===================== Streamlit UI =====================

st.set_page_config(
    page_title="PDF Auswertung Logistik",
    layout="wide",
)

st.markdown(
    """
    # 📦 PDF Auswertung Logistik
    Lade einen Verladeplan als PDF hoch und erzeuge eine Excel-Auswertung
    mit Bauteilen, Pritschen und Gewichten.
    """
)

uploaded_file = st.file_uploader("PDF-Verladeplan hochladen", type=["pdf"])

if uploaded_file is None:
    st.info("Bitte zuerst eine PDF-Datei hochladen.")
    st.stop()

pdf_bytes = uploaded_file.getvalue()

with st.spinner("PDF wird analysiert …"):
    df_all, pritsche_ids, pritschenarten, einlage_typen = extract_data_from_pdf(pdf_bytes)

st.success("PDF erfolgreich eingelesen.")

# ----- Sidebar: Filter & Einstellungen -----
st.sidebar.header("⚙️ Einstellungen")

selected_pritschenarten = st.sidebar.multiselect(
    "Pritschen-Bezeichnungen (Prefix) auswählen",
    options=pritschenarten,
    default=pritschenarten,
    help="Es werden alle Pritschen berücksichtigt, deren Name mit diesem Prefix beginnt (z.B. PB → PB1, PB2 ...).",
)

selected_einlagen = st.sidebar.multiselect(
    "Einlagen, die NICHT ausgewertet werden sollen",
    options=einlage_typen,
    default=einlage_typen,  # Standard: alle Einlagen ignorieren
    help="Alle hier ausgewählten Einlagen werden aus der Bauteil-Liste entfernt.",
)

start_button = st.sidebar.button("🔍 Auswertung starten")

if not start_button:
    st.stop()

if not selected_pritschenarten:
    st.error("Bitte mindestens eine Pritschen-Bezeichnung auswählen.")
    st.stop()

# ===================== Filter-Logik =====================

# Nur gewünschte Pritschenarten
df_filtered = df_all[df_all["Pritschenart"].isin(selected_pritschenarten)].copy()

# Einlagen raus, die ignoriert werden sollen
mask_ignorieren = df_filtered["Ist_Einlage"] & df_filtered["EinlageTyp"].isin(selected_einlagen)
df_bauteile = df_filtered[~mask_ignorieren].copy()

# Bauteil-Nummern als Zahlen (für Sortierung & Excel)
df_bauteile["Bauteil"] = pd.to_numeric(df_bauteile["Bauteil_raw"], errors="coerce")
df_bauteile = df_bauteile.dropna(subset=["Bauteil"])

# Pritsche in Prefix + Nummer splitten, um PB1, PB2, ... richtig zu sortieren
pb_split = df_bauteile["PB"].str.extract(r"(?P<prefix>[A-ZÄÖÜ]+)(?P<num>\d+)")
df_bauteile["PB_prefix"] = pb_split["prefix"]
df_bauteile["PB_num"] = pd.to_numeric(pb_split["num"], errors="coerce")

df_bauteile.sort_values(
    by=["PB_prefix", "PB_num", "Bauteil"],
    inplace=True
)

# Export-Ansicht: Bauteile-Tabelle
bauteile_export = df_bauteile[["Bauteil", "PB", "Gewicht [kg]"]].copy()

# Zusammenfassung je Pritsche
summary_per_pb = (
    bauteile_export.groupby("PB")
    .agg(
        Anzahl_Elemente=("Bauteil", "count"),
        Gesamtgewicht_kg=("Gewicht [kg]", "sum"),
    )
    .reset_index()
)

gesamt_row = pd.DataFrame(
    {
        "PB": ["Gesamt"],
        "Anzahl_Elemente": [summary_per_pb["Anzahl_Elemente"].sum()],
        "Gesamtgewicht_kg": [summary_per_pb["Gesamtgewicht_kg"].sum()],
    }
)

summary_gesamt = pd.concat([summary_per_pb, gesamt_row], ignore_index=True)

# ===================== Anzeige im Frontend =====================

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Pritschen (ausgewählt)", len(summary_per_pb))
with col2:
    st.metric("Elemente gesamt", int(gesamt_row["Anzahl_Elemente"].iloc[0]))
with col3:
    st.metric("Gesamtgewicht", f"{gesamt_row['Gesamtgewicht_kg'].iloc[0]:.1f} kg")

st.subheader("Bauteile (nach Pritsche & Bauteil sortiert)")
st.dataframe(bauteile_export.head(50))

st.subheader("Zusammenfassung je Pritsche")
st.dataframe(summary_gesamt)

# ===================== Excel-Export =====================

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
