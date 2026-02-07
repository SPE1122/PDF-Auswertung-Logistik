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
    oder '7 10 Bund 1 3 . ...'
    und gibt eine Liste von bis zu 4 Tupeln (Bauteil, Gewicht) zurück.
    """
    tokens = line.split()
    if len(tokens) < 3:
        return []

    # Prüfen, ob die Zeile mit Zeilennummer (1-7) und optional L/R beginnt
    if re.match(r"^[1-7]\b", tokens[0]):
        if len(tokens) > 1 and tokens[1] in ["L", "R"]:
            main_tokens = tokens[2:]
        else:
            main_tokens = tokens[1:]
    else:
        # Kopfzeile ohne 1-7 (z.B. Einlage 80 . 1 . ...)
        main_tokens = tokens

    # Wir suchen die Gewichte (7 Tokens am Ende)
    # Wenn weniger als 7 Tokens da sind, versuchen wir trotzdem Bauteile zu finden
    if len(main_tokens) >= 7:
        weights_raw = main_tokens[-7:-3]
        try:
            # Gewichte validieren: Müssen Zahlen sein
            weights = []
            for w in weights_raw:
                try:
                    weights.append(float(w))
                except:
                    weights.append(0.0)
        except:
            weights = [0.0] * 4
        element_tokens = main_tokens[:-7]
    else:
        weights = [0.0] * 4
        element_tokens = main_tokens

    elements = []
    i = 0
    # Wir begrenzen die Suche nach Bauteilen auf Tokens, die VOR den Gewichtsspalten stehen könnten.
    limit = len(element_tokens)
    
    while i < limit and len(elements) < 4:
        tok = element_tokens[i]
        
        # Ignoriere Footer-Zeilen Keywords und alles danach
        if tok in ["Ladehöhe:", "Gesammtgewicht", "ca.:", "Tonnen", "Zusätzliches", "Verlade-Material:", "Bemerkungen:"]:
            break
            
        if tok == ".":
            elements.append(None)
            i += 1
        elif tok == "Einlage" and i + 1 < limit:
            elements.append(f"{tok} {element_tokens[i + 1]}")
            i += 2
        elif tok == "Bund" and i + 1 < limit:
            elements.append(f"{tok} {element_tokens[i + 1]}")
            i += 2
        else:
            # Bauteil muss entweder eine Zahl (evtl mit *) sein
            if re.match(r"^\d+\*?$", tok):
                elements.append(tok)
            elif tok.startswith("Einlage") or tok.startswith("Bund"):
                elements.append(tok)
            else:
                # Unbekannter Token, ignorieren
                pass
            i += 1

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
    seen_parts = set() # Um Duplikate zu vermeiden

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

            # "PB 100" -> PB100
            m_id = re.search(r"([A-ZÄÖÜ]+\s*\d+)", pritsche_full)
            if m_id:
                pritsche_id = re.sub(r"\s+", "", m_id.group(1))
            else:
                pritsche_id = pritsche_full.split()[0]

            # Prefix / Pritschenart (PB, PW, ...)
            m3 = re.match(r"([A-ZÄÖÜ]+)", pritsche_id)
            pritschenart = m3.group(1) if m3 else pritsche_id

            # Tabellenzeilen parsen
            for line in text.splitlines():
                # Normales Parsing der 4 Positionen
                pairs = parse_row(line)
                for bauteil, gewicht in pairs:
                    if bauteil is None or bauteil == ".":
                        continue

                    # Eindeutiger Schlüssel pro Seite/Pritsche/Position/Name
                    # Da wir Zeilenweise lesen, nutzen wir den Namen + Pritsche + Seite
                    # Wir müssen vorsichtig sein, da manche Bauteile mehrfach vorkommen können
                    # Aber in einer PDF-Zeile sind sie meist eindeutig platziert.
                    
                    ist_einlage = isinstance(bauteil, str) and bauteil.startswith("Einlage ")
                    if ist_einlage:
                        einlage_typen.add(bauteil)

                    records.append(
                        {
                            "Bauteil_raw": str(bauteil),
                            "PB": pritsche_id,
                            "Pritschenart": pritschenart,
                            "Gewicht [kg]": gewicht,
                            "Seite": page_index,
                            "Ist_Einlage": ist_einlage,
                            "EinlageTyp": bauteil if ist_einlage else None,
                        }
                    )

    df = pd.DataFrame(records)
    
    pritsche_ids = sorted(df["PB"].unique()) if not df.empty else []
    pritschenarten = sorted(df["Pritschenart"].unique()) if not df.empty else []
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

# Bauteil-Sortierung vorbereiten
def get_sort_val(val):
    clean = str(val).replace("*", "").strip()
    try:
        return float(clean)
    except:
        return 999999 # Text ans Ende

df_bauteile["Bauteil_sort"] = df_bauteile["Bauteil_raw"].apply(get_sort_val)
df_bauteile["Ist_Rohr"] = df_bauteile["Bauteil_raw"].str.contains(r"\*", na=False)

# Pritsche in Prefix + Nummer splitten
pb_split = df_bauteile["PB"].str.extract(r"(?P<prefix>[A-ZÄÖÜ]+)(?P<num>\d*)")
df_bauteile["PB_prefix"] = pb_split["prefix"]
df_bauteile["PB_num"] = pd.to_numeric(pb_split["num"], errors="coerce").fillna(0)

df_bauteile.sort_values(
    by=["PB_prefix", "PB_num", "Bauteil_sort", "Bauteil_raw"],
    inplace=True
)

# Export-Ansicht: Bauteile-Tabelle
# Wir filtern hier die 'Bund' Einträge aus der Bauteil-Liste heraus
bauteile_export = df_bauteile[~df_bauteile["Bauteil_raw"].str.contains("Bund", case=False, na=False)].copy()
bauteile_export = bauteile_export[["Bauteil_raw", "PB", "Gewicht [kg]", "Ist_Rohr"]]
bauteile_export.rename(columns={"Bauteil_raw": "Bauteil"}, inplace=True)

# Zusammenfassung je Pritsche
# Wir zählen Bauteile und vermerken Bunde (aus dem ursprünglichen df_bauteile, das noch Bunde enthält)
def get_summary(df_with_bunds, df_summary_base):
    # Gruppieren nach Pritsche (basierend auf der gefilterten Liste für korrekte Anzahl)
    summary = df_summary_base.groupby("PB").agg(
        Anzahl_Elemente=("Bauteil", "count"),
        Gesamtgewicht_kg=("Gewicht [kg]", "sum")
    ).reset_index()
    
    # Bunde für jede Pritsche aus dem ursprünglichen DF finden
    bunde_per_pb = df_with_bunds[df_with_bunds["Bauteil_raw"].astype(str).str.contains("Bund", case=False, na=False)].groupby("PB")["Bauteil_raw"].unique()
    bunde_dict = bunde_per_pb.apply(lambda x: ", ".join(map(str, x))).to_dict()
    
    summary["Info"] = summary["PB"].map(bunde_dict).fillna("")
    return summary

summary_per_pb = get_summary(df_bauteile, bauteile_export)

# Gesamt-Zeile für die Anzeige (ohne Info-Text für Gesamt)
gesamt_row = pd.DataFrame(
    {
        "PB": ["Gesamt"],
        "Anzahl_Elemente": [summary_per_pb["Anzahl_Elemente"].sum()],
        "Gesamtgewicht_kg": [summary_per_pb["Gesamtgewicht_kg"].sum()],
        "Info": [""]
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

# Styling für Rohre (*)
def highlight_rohr(row):
    # Nur Textfarbe rot für Bauteile mit *
    # Wir prüfen den Bauteil-Text direkt
    is_rohr = "*" in str(row["Bauteil"])
    return ['color: red' if is_rohr else '' for _ in row.index]

# Spalte Ist_Rohr in der Anzeige verstecken
st.dataframe(
    bauteile_export.drop(columns=["Ist_Rohr"]).head(1000).style.apply(highlight_rohr, axis=1)
)

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
