import math
import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go


# -------------------------------------------------------
# LOGIC 1: Calculate expected coal flow and mills required
# -------------------------------------------------------
def calculate_mill_requirement(plant_gross_heat_rate, load_mw, gross_calorific_value, allowable_coal_flow_per_mill):
    if plant_gross_heat_rate < 0:
        raise ValueError("Plant gross heat rate cannot be negative.")
    if load_mw < 0:
        raise ValueError("Plant load cannot be negative.")
    if gross_calorific_value <= 0:
        raise ValueError("Gross calorific value must be greater than zero.")
    if allowable_coal_flow_per_mill <= 0:
        raise ValueError("Allowable coal flow per mill must be greater than zero.")
    expected_coal_flow = (plant_gross_heat_rate * load_mw) / gross_calorific_value
    mills_required = math.ceil(expected_coal_flow / allowable_coal_flow_per_mill)
    return expected_coal_flow, mills_required


# -------------------------------------------------------
# LOGIC 2: Classify mill status from Health Index
# -------------------------------------------------------
def get_mill_status(hi):
    if pd.isna(hi) or hi <= 0:
        return "Not Available"
    if hi > 70:
        return "Available"
    elif hi >= 60:
        return "Standby"
    elif hi >= 50:
        return "Emergency"
    return "Not Available"


# -------------------------------------------------------
# LOGIC 3: Recommend RUN, STANDBY, or STOP
# -------------------------------------------------------
def get_run_stop_status(mill_status, mills_required, mill_priority):
    if mill_status != "Available":
        return "STOP"
    if mill_priority <= mills_required:
        return "RUN"
    return "STANDBY"

st.set_page_config(page_title="Mill Scheduling Tool", layout="wide")
st.title("Mill Scheduling Tool")

uploaded_workbook = st.file_uploader(
    "Upload Smart Mill Scheduling workbook",
    type=["xlsx"],
    key="workbook"
)

if uploaded_workbook:

    workbook = pd.ExcelFile(uploaded_workbook)
    if "INPUT SHEET" not in workbook.sheet_names:
        st.error("The uploaded workbook must contain an 'INPUT SHEET' tab.")
        st.stop()

    input_sheet = pd.read_excel(workbook, sheet_name="INPUT SHEET", header=None).fillna("")
    df = input_sheet.iloc[:, :5].copy()
    df.columns = ["SlNo", "Description", "UoM", "Design", "Operating"]

    data = {}
    for _, row in df.iterrows():
        key = str(row["Description"]).strip().upper()
        data[key] = {"Design": row["Design"], "Operating": row["Operating"]}

    # -------------------------------------------------------
    # Health inputs, optimal limits, and calculated scores share this sheet.
    hi_sheet = input_sheet

    MILLS = ["MILL-A", "MILL-B", "MILL-C", "MILL-D", "MILL-E", "MILL-F"]

    # INPUT SHEET columns: H=description, J=design, K=optimal,
    # L:Q=Mill A-F operating values, S:X=Mill A-F scores.
    OP_COLS = {
        "MILL-A": 11, "MILL-B": 12, "MILL-C": 13,
        "MILL-D": 14, "MILL-E": 15, "MILL-F": 16
    }
    SCORE_COLS = {
        "MILL-A": 18, "MILL-B": 19, "MILL-C": 20,
        "MILL-D": 21, "MILL-E": 22, "MILL-F": 23
    }

    LOWER_BETTER = {
        # Electrical
        "MOTOR BEARING VIBRATION", "MOTOR BEARING TEMPERATURE",
        "MILL POWER CONSUMPTION", "TEN DELTA",
        # Mechanical
        "MILL BEARING VIBRATION",
        "MILL/FEEDER ABNORMAL TRIP IN LAST QUARTER", "RUNNING HOURS SINCE LAST MAINTENANCE",
        # Operational — temperatures that are lower-better (overheating risk)
        "INLET TEMPERATURE", "OUTLET TEMPERATURE",
        "BOWL DP", "MILL TO SEAL AIR DP", "MILL SPECIFIC POWER CONSUMPTION",
        "PRIMARY AIR FLOW TO COAL RATIO", "COAL PIPE TEMPERATURE", "PA INLET PRESSURE",
        # NOTE: MILL BEARING TEMPERATURE is intentionally NOT here (higher=better for bearing warmth)
    }

    HEALTHY_PARAMS = {
        "MILL FINENESS", "MILL REJECT CONDITION",
        "FLAME INTENSITY HEALTHINESS %", "INERT STEAM AVAILABILITY",
    }

    param_row = {}
    for i in range(len(hi_sheet)):
        label = str(hi_sheet.iloc[i, 7]).strip().upper() if hi_sheet.shape[1] > 7 else ""
        if label:
            param_row[label] = i

    # -------------------------------------------------------
    # 1. BASIC CRITERIA CHECK
    # -------------------------------------------------------
    st.header("1. BASIC CRITERIA CHECK")

    criteria = []

    def check_equal(desc, value):
        return data[desc]["Operating"] == value

    def check_greater_than_60(desc):
        return float(data[desc]["Operating"]) > 0.60 * float(data[desc]["Design"])

    criteria.append(["NUMBER OF FD FANS IN SERVICE",       "Nos", check_equal("NUMBER OF FD FANS IN SERVICE", 2)])
    criteria.append(["NUMBER OF ID FANS IN SERVICE",       "Nos", check_equal("NUMBER OF ID FANS IN SERVICE", 2)])
    criteria.append(["NUMBER OF PA FANS IN SERVICE",       "Nos", check_equal("NUMBER OF PA FANS IN SERVICE", 2)])
    criteria.append(["NUMBER OF APHs IN SERVICE",          "Nos", check_equal("NUMBER OF APHS IN SERVICE", 2)])
    criteria.append(["NUMBER OF SEAL AIR FANS IN SERVICE", "Nos", check_equal("NUMBER OF SEAL AIR FANS IN SERVICE", 1)])

    start_row = None
    for i in range(len(df)):
        if str(df.iloc[i, 1]).strip().upper() == "MILL AVAILABILITY STATUS":
            start_row = i + 1
            break

    if start_row is None:
        st.error("MILL AVAILABILITY STATUS section not found.")
        st.stop()

    mill_rows = []
    for i in range(start_row, len(df)):
        desc = str(df.iloc[i, 1]).strip()
        if desc == "" or desc.lower() == "nan":
            break
        mill_rows.append(df.iloc[i])

    mill_df = pd.DataFrame(mill_rows).reset_index(drop=True)

    avail_col = mill_df["Design"].astype(str).str.strip().str.upper()
    not_available_count = (avail_col == "NOT AVAILABLE").sum()
    mill_under_maintenance = not_available_count < 2

    criteria.append(["MILL UNDER MAINTENANCE",        "-",   mill_under_maintenance])
    criteria.append(["LOAD > 60% OF DESIGN",          "MW",  check_greater_than_60("LOAD")])
    criteria.append(["MAIN STEAM FLOW >60%",          "TPH", check_greater_than_60("MAIN STEAM FLOW")])
    criteria.append(["TOTAL AIR FLOW >60%",           "TPH", check_greater_than_60("TOTAL AIR FLOW")])
    criteria.append(["TOTAL SECONDARY AIR FLOW >60%", "TPH", check_greater_than_60("TOTAL SECONDARY AIR FLOW")])
    criteria.append(["TOTAL COAL FLOW >60%",          "TPH", check_greater_than_60("TOTAL COAL FLOW")])

    result_df = pd.DataFrame(criteria, columns=["Criteria", "Unit", "Result"])
    st.dataframe(result_df, use_container_width=True)

    st.subheader("LOGIC")
    if result_df["Result"].all():
        st.success("✅ Proceed for Mill Scheduling")
    else:
        st.error("❌ STOP")

    # -------------------------------------------------------
    # 2. MILL AVAILABILITY STATUS
    # -------------------------------------------------------
    st.header("2. MILL AVAILABILITY STATUS")

    mills = []
    for i in range(len(mill_df)):
        avail = str(mill_df.iloc[i]["Design"]).strip().upper()
        raw_name = str(mill_df.iloc[i]["Description"]).replace(" STATUS", "").strip()
        # Normalize "MILL X" -> "MILL-X" to match MILLS list
        raw_name = re.sub(r'^MILL\s+([A-F])$', r'MILL-\1', raw_name.upper())
        current_row = param_row.get("MOTOR CURRENT")
        current = 0.0
        if current_row is not None:
            current_value = hi_sheet.iloc[current_row, OP_COLS[raw_name]]
            try:
                current = float(current_value)
            except (TypeError, ValueError):
                current = 0.0
        running = avail == "AVAILABLE" and current > 5
        mills.append({
            "Mill":         raw_name,
            "Availability": avail,
            "Running":      running,
            "Status":       "RUNNING" if running else "STOP"
        })

    adj = []
    for i in range(len(mills)):
        if i == 0:
            adj.append(1.0 if mills[i + 1]["Running"] else 0.0)
        elif i == len(mills) - 1:
            adj.append(1.0 if mills[i - 1]["Running"] else 0.0)
        else:
            prev = mills[i - 1]["Running"]
            nxt  = mills[i + 1]["Running"]
            adj.append(1.0 if (prev and nxt) else 0.5 if (prev or nxt) else 0.0)

    output_rows = []
    for i, m in enumerate(mills):
        output_rows.append([m["Mill"], m["Availability"], m["Status"], round(adj[i], 1)])

    output_df = pd.DataFrame(output_rows, columns=["Mill", "Availability", "Status", "ADJ_MILL"])
    output_df["ADJ_MILL"] = output_df["ADJ_MILL"].map("{:.1f}".format)

    def color_status(val):
        return "color:green;font-weight:bold" if val == "RUNNING" else "color:red;font-weight:bold"

    st.dataframe(
        output_df.style.map(color_status, subset=["Status"]),
        use_container_width=True
    )

    # -------------------------------------------------------
    # 3. ESTIMATION OF MILL HEALTH INDEX
    # -------------------------------------------------------
    st.header("3. ESTIMATION OF MILL HEALTH INDEX")

    CAT_W = {"ELECTRICAL": 0.3, "MECHANICAL": 0.2, "OPERATIONAL": 0.5}

    PARAMS = [
        ("INSULATION RESISTANCE",                     "ELECTRICAL",  0.10),
        ("MOTOR WINDING TEMPERATURE",                 "ELECTRICAL",  0.10),
        ("POLARISATION INDEX",                        "ELECTRICAL",  0.10),
        ("TEN DELTA",                                 "ELECTRICAL",  0.10),
        ("MOTOR BEARING VIBRATION",                   "ELECTRICAL",  0.20),
        ("MOTOR BEARING TEMPERATURE",                 "ELECTRICAL",  0.20),
        ("MILL POWER CONSUMPTION",                    "ELECTRICAL",  0.20),
        ("MILL BEARING VIBRATION",                    "MECHANICAL",  0.30),
        ("MILL BEARING TEMPERATURE",                  "MECHANICAL",  0.30),
        ("MILL/FEEDER ABNORMAL TRIP IN LAST QUARTER", "MECHANICAL",  0.20),
        ("RUNNING HOURS SINCE LAST MAINTENANCE",      "MECHANICAL",  0.20),
        ("FEEDER COAL FLOW",                          "OPERATIONAL", 0.03),
        ("PA FLOW",                                   "OPERATIONAL", 0.03),
        ("INLET TEMPERATURE",                         "OPERATIONAL", 0.08),
        ("BOWL DP",                                   "OPERATIONAL", 0.08),
        ("OUTLET TEMPERATURE",                        "OPERATIONAL", 0.05),
        ("PA INLET PRESSURE",                         "OPERATIONAL", 0.10),
        ("MILL TO SEAL AIR DP",                       "OPERATIONAL", 0.07),
        ("MILL FINENESS",                             "OPERATIONAL", 0.05),
        ("COAL PIPE TEMPERATURE",                     "OPERATIONAL", 0.05),
        ("LUBE OIL PRESSURE",                         "OPERATIONAL", 0.03),
        ("MILL REJECT CONDITION",                     "OPERATIONAL", 0.05),
        ("FLAME INTENSITY HEALTHINESS %",             "OPERATIONAL", 0.03),
        ("INERT STEAM AVAILABILITY",                  "OPERATIONAL", 0.05),
        ("MILL SPECIFIC POWER CONSUMPTION",           "OPERATIONAL", 0.15),
        ("PRIMARY AIR FLOW TO COAL RATIO",            "OPERATIONAL", 0.15),
    ]

    TRIPS_PARAM = "MILL/FEEDER ABNORMAL TRIP IN LAST QUARTER"
    HOURS_PARAM = "RUNNING HOURS SINCE LAST MAINTENANCE"

    def _to_float(val):
        """Convert to float, stripping % signs (handles '1%', '0.80%' etc)."""
        s = str(val).strip().rstrip("%")
        return float(s) if s not in ("", "nan", "none", "NaN", "None") and s.replace(".", "", 1).lstrip("-").isdigit() else None

    def compute_score(p, op_raw, des_raw, opt_raw):
        """
        Scores computed exactly as per Excel INPUT SHEET formulas.
        opt = OPTIMAL LIMIT (col K in Excel) derived from design value.
        All formulas reference $K (optimal), not design directly.
        """
        p = p.upper()

        # --- HEALTHY/UNHEALTHY binary params ---
        if p in HEALTHY_PARAMS:
            return 1.0 if str(op_raw).strip().upper() == "HEALTHY" else 0.0

        op  = _to_float(op_raw)
        des = _to_float(des_raw)
        opt = _to_float(opt_raw)

        if op is None or opt is None:
            return 0.0

        # ── LOWER IS BETTER: IF(op<0.9*opt,1,IF(op<=0.98*opt,0.5,0)) ──────
        # Motor/Mill bearing vibration & temperature, winding temp,
        # inlet/outlet/coal pipe temp, bowl DP, mill-to-seal air DP,
        # mill power consumption (uses 0.95/1.0 thresholds), feeder coal flow
        if p in (
            "MOTOR WINDING TEMPERATURE",
            "MOTOR BEARING VIBRATION",
            "MOTOR BEARING TEMPERATURE",
            "MILL BEARING VIBRATION",
            "MILL BEARING TEMPERATURE",
            "INLET TEMPERATURE",
            "BOWL DP",
            "OUTLET TEMPERATURE",
            "MILL TO SEAL AIR DP",
            "COAL PIPE TEMPERATURE",
            "FEEDER COAL FLOW",
        ):
            # Excel: IF(op < 0.9*opt, 1, IF(op <= 0.98*opt, 0.5, 0))
            return 1.0 if op < 0.9 * opt else (0.5 if op <= 0.98 * opt else 0.0)

        # ── MILL POWER CONSUMPTION: IF(op<0.95*opt,1,IF(op<=1*opt,0.5,0)) ─
        if p == "MILL POWER CONSUMPTION":
            return 1.0 if op < 0.95 * opt else (0.5 if op <= opt else 0.0)

        # ── MILL SPECIFIC POWER: IF(op<0.95*opt,1,IF(op<=1*opt,0.5,0)) ────
        if p == "MILL SPECIFIC POWER CONSUMPTION":
            return 1.0 if op < 0.95 * opt else (0.5 if op <= opt else 0.0)

        # ── TRIPS: IF(op<opt,1,IF(op<=2*opt,0.5,0))  opt=1 hardcoded ──────
        if p == "MILL/FEEDER ABNORMAL TRIP IN LAST QUARTER":
            return 1.0 if op < opt else (0.5 if op <= 2 * opt else 0.0)

        # ── RUNNING HOURS: IF(op<opt,1,IF(op<=2*opt,0.5,0))  opt=des*0.8 ──
        if p == "RUNNING HOURS SINCE LAST MAINTENANCE":
            return 1.0 if op < opt else (0.5 if op <= 2 * opt else 0.0)

        # ── HIGHER IS BETTER: IF(op>opt,1,0) ────────────────────────────────
        # Insulation resistance: opt=design, Polarisation index: opt=0.9*design
        if p in ("INSULATION RESISTANCE", "POLARISATION INDEX"):
            return 1.0 if op > opt else 0.0

        # ── TEN DELTA: IF(op<opt,1,0)  opt=design ───────────────────────────
        if p == "TEN DELTA":
            return 1.0 if op < opt else 0.0

        # ── PA FLOW: IF(op<0.6*opt,0,IF(op<=0.98*opt,0.5,1)) ───────────────
        if p == "PA FLOW":
            return 0.0 if op < 0.6 * opt else (0.5 if op <= 0.98 * opt else 1.0)

        # ── PA INLET PRESSURE: IF(op<0.8*opt,0,IF(op<=0.9*opt,0.5,1)) ─────
        if p == "PA INLET PRESSURE":
            return 0.0 if op < 0.8 * opt else (0.5 if op <= 0.9 * opt else 1.0)

        # ── LUBE OIL PRESSURE: IF(op<0.9*opt,0,IF(op<=0.98*opt,0.5,1)) ────
        if p == "LUBE OIL PRESSURE":
            return 0.0 if op < 0.9 * opt else (0.5 if op <= 0.98 * opt else 1.0)

        # ── PRIMARY AIR FLOW TO COAL RATIO: IF(op<0.8*opt,0,IF(op<=0.9*opt,0.5,1))
        if p == "PRIMARY AIR FLOW TO COAL RATIO":
            return 0.0 if op < 0.8 * opt else (0.5 if op <= 0.9 * opt else 1.0)

        return 0.0

    def get_score(param_label, mill):
        row_idx = param_row.get(param_label.upper())
        if row_idx is None:
            return 0.0
        # Always compute from op/design/optimal columns — never read stale pre-baked
        # score columns first, since user may update op values without Excel recalculating them
        ncols = hi_sheet.shape[1]
        op_col    = OP_COLS[mill]
        score_col = SCORE_COLS[mill]
        if op_col < ncols and 9 < ncols and 10 < ncols:
            op_raw  = hi_sheet.iloc[row_idx, op_col]
            des_raw = hi_sheet.iloc[row_idx, 9]
            opt_raw = hi_sheet.iloc[row_idx, 10]
            return compute_score(param_label, op_raw, des_raw, opt_raw)
        if score_col < ncols:
            s = _to_float(hi_sheet.iloc[row_idx, score_col])
            if s is not None and 0.0 <= s <= 1.0:
                return s
        return 0.0

    mill_hi     = {}
    detail_rows = []

    for mill in MILLS:
        mill_avail = output_df.loc[output_df["Mill"] == mill, "Availability"]
        avail_str  = str(mill_avail.values[0]).upper() if not mill_avail.empty else ""
        is_available = avail_str == "AVAILABLE"

        if not is_available:
            mill_hi[mill] = 0.0
            continue

        total      = 0.0
        for param, cat, pw in PARAMS:
            score   = get_score(param, mill)
            norm_w  = round(CAT_W[cat] * pw, 4)
            contrib = round(score * norm_w, 4)
            total  += contrib
            detail_rows.append({
                "Mill": mill, "Category": cat, "Parameter": param,
                "Score": score, "Param Weight": f"{int(pw*100)}%",
                "Norm Weight": norm_w, "Contribution": contrib
            })

        mill_hi[mill] = round(total * 100, 2)

    hi_summary = pd.DataFrame([
        {"Mill": m, "Health Index": mill_hi[m]} for m in MILLS
    ])

    def color_hi(val):
        if val >= 80:   return "color:green;font-weight:bold"
        elif val >= 60: return "color:orange;font-weight:bold"
        return "color:red;font-weight:bold"

    st.dataframe(
        hi_summary.style.map(color_hi, subset=["Health Index"]),
        use_container_width=True
    )

    with st.expander("View Detailed Health Index Breakdown"):
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True)

    with st.expander("🔍 Debug: Param name mismatches (score=0 & row not found)"):
        not_found = [p for p, _, _ in PARAMS if param_row.get(p.upper()) is None]
        zero_scores = [
            {"Mill": r["Mill"], "Parameter": r["Parameter"], "Score": r["Score"]}
            for r in detail_rows if r["Score"] == 0.0
        ]
        st.write("**Params not found in hi_sheet (label mismatch):**", not_found if not_found else "None")
        st.write("**All param labels found in hi_sheet:**")
        st.write(sorted(param_row.keys()))
        st.write("**Zero-score entries:**")
        st.dataframe(pd.DataFrame(zero_scores) if zero_scores else pd.DataFrame([{"info": "No zero scores"}]))

    # -------------------------------------------------------
    # 5. MILL SCHEDULING OUTPUT
    # -------------------------------------------------------
    st.header("4. MILL SCHEDULING OUTPUT")

    def fval(key, col):
        raw = data.get(key.upper(), {}).get(col, 0) or 0
        return _to_float(raw) or 0.0

    def fval_any(keys, col):
        """Try multiple key variants; return first non-zero match.
        Also tries substring matching against all data keys as a last resort."""
        for k in keys:
            v = fval(k, col)
            if v != 0.0:
                return v
        # Substring fallback: find any data key that contains one of the keywords
        for k in keys:
            ku = k.upper()
            for dk in data:
                if ku in dk or dk in ku:
                    v = _to_float(data[dk].get(col, 0) or 0)
                    if v is not None and v != 0.0:
                        return v
        return 0.0

    spray_design = (
        fval("SUPER HEATER SPRAY", "Design") + fval("REHEATER SPRAY", "Design")
    ) / fval("MAIN STEAM FLOW", "Design") if fval("MAIN STEAM FLOW", "Design") else 0.0
    spray_op = (
        fval("SUPER HEATER SPRAY", "Operating") + fval("REHEATER SPRAY", "Operating")
    ) / fval("MAIN STEAM FLOW", "Operating") if fval("MAIN STEAM FLOW", "Operating") else 0.0
    metal_design = fval_any(["HIGHEST METAL TEMPERATURE", "MAX METAL TEMPERATURE",
                             "METAL TEMPERATURE", "HIGHEST METAL TEMP"], "Design")
    metal_op     = fval_any(["HIGHEST METAL TEMPERATURE", "MAX METAL TEMPERATURE",
                             "METAL TEMPERATURE", "HIGHEST METAL TEMP"], "Operating")
    aph_design   = fval_any(["APH INLET FLUE GAS TEMPERATURE", "APH INLET TEMP",
                             "APH INLET FG TEMP", "APH INLET FLUE GAS TEMP"], "Design")
    aph_op       = fval_any(["APH INLET FLUE GAS TEMPERATURE", "APH INLET TEMP",
                             "APH INLET FG TEMP", "APH INLET FLUE GAS TEMP"], "Operating")
    gcv_design   = fval_any(["GROSS CALORIFIC VALUE", "GCV", "CALORIFIC VALUE",
                             "GROSS CALORIFIC VALUE (GCV)"], "Design")
    gcv_op       = fval_any(["GROSS CALORIFIC VALUE", "GCV", "CALORIFIC VALUE",
                             "GROSS CALORIFIC VALUE (GCV)"], "Operating")
    load_design  = fval("LOAD", "Design")
    load_op      = fval("LOAD", "Operating")

    # --- LOGIC 1: Compute expected coal flow and mills required ---
    plant_gross_heat_rate        = fval_any(["PLANT GROSS HEAT RATE", "GROSS HEAT RATE",
                                             "PLANT HEAT RATE"], "Operating")
    allowable_coal_flow_per_mill = fval_any(["ALLOWABLE COAL FLOW PER MILL", "COAL FLOW PER MILL",
                                             "MAX COAL FLOW PER MILL"], "Design")

    # Fallback: if not in data, derive from existing operating values
    if plant_gross_heat_rate <= 0:
        plant_gross_heat_rate = fval("PLANT GROSS HEAT RATE", "Design") or 2300.0
    if allowable_coal_flow_per_mill <= 0:
        allowable_coal_flow_per_mill = 75.0  # TPH default
    if gcv_op <= 0:
        gcv_op = gcv_design if gcv_design > 0 else 3800.0
    if load_op <= 0:
        load_op = load_design

    if plant_gross_heat_rate > 0 and load_op >= 0 and gcv_op > 0 and allowable_coal_flow_per_mill > 0:
        expected_coal_flow, mills_required = calculate_mill_requirement(
            plant_gross_heat_rate=plant_gross_heat_rate,
            load_mw=load_op,
            gross_calorific_value=gcv_op,
            allowable_coal_flow_per_mill=allowable_coal_flow_per_mill
        )
    else:
        expected_coal_flow = 0.0
        mills_required = int(fval("NO. OF MILLS IN SERVICE", "Operating") or 4)

    st.info(
        f"Expected Coal Flow: **{round(expected_coal_flow, 2)} TPH** | "
        f"Mills Required: **{mills_required}**"
    )

    def dev_pct(op, design):
        return ((op - design) / design * 100) if design else 0

    spray_dev = dev_pct(spray_op, spray_design)
    metal_dev = dev_pct(metal_op, metal_design)
    aph_dev   = dev_pct(aph_op,   aph_design)
    gcv_dev   = dev_pct(gcv_op,   gcv_design)
    load_dev  = dev_pct(load_op,  load_design)

    with st.expander("🔍 Debug: Bias input values & File 1 keys"):
        st.write("**Spray:**",  spray_design, "/", spray_op,  "→ dev%:", round(spray_dev, 2))
        st.write("**Metal:**",  metal_design, "/", metal_op,  "→ dev%:", round(metal_dev, 2))
        st.write("**APH:**",    aph_design,   "/", aph_op,    "→ dev%:", round(aph_dev,   2))
        st.write("**GCV:**",    gcv_design,   "/", gcv_op,    "→ dev%:", round(gcv_dev,   2))
        st.write("**Load:**",   load_design,  "/", load_op,   "→ dev%:", round(load_dev,  2))
        st.write("**PGHR:**",   plant_gross_heat_rate, "  |  **AllowCoalFlow:**", allowable_coal_flow_per_mill)
        st.write("**All File 1 keys:**", sorted(data.keys()))

    def get_spray_bias(mill, dev):
        if mill in ("MILL-A", "MILL-B", "MILL-C"):
            return 0 if dev <= 20 else 5
        elif mill == "MILL-D":
            return 5 if dev <= 0 else (0 if dev <= 20 else -5)
        elif mill == "MILL-E":
            return 10 if dev <= 0 else (0 if dev <= 20 else -10)
        else:
            return 5 if dev <= 0 else (0 if dev <= 20 else -20)

    def get_metal_bias(mill, dev):
        if mill in ("MILL-A", "MILL-B", "MILL-C"):
            return 5 if dev > 2 else 0
        elif mill == "MILL-D":
            return -5 if dev > 2 else 0
        else:
            return -10 if dev > 2 else 0

    def get_gcv_bias(mill, dev):
        if mill in ("MILL-A", "MILL-B", "MILL-C"):
            return 5 if dev > 5 else (-5 if dev < -5 else 0)
        else:
            return -5 if dev > 5 else (5 if dev < -5 else 0)

    def get_load_bias(mill, dev):
        if mill in ("MILL-A", "MILL-F"):
            return 0
        else:
            return 3 if dev <= -20 else 0

    aph_bias = -5 if aph_dev > 5 else 0

    sched = []
    for mill in MILLS:
        hi = mill_hi[mill]

        # Classify mill status from the workbook health-index thresholds.
        status = get_mill_status(hi)

        # adj_val = float(str(output_df.loc[output_df["Mill"] == mill, "ADJ_MILL"].values[0]))
        # if mill in ("MILL-E", "MILL-F"):
        #     adj_bias = 0 if adj_val == 1 else -5
        # else:
        #     adj_bias = 0 if adj_val > 0.4 else -5

        adj_val = float(str(output_df.loc[output_df["Mill"] == mill, "ADJ_MILL"].values[0]))
        mill_status_str = str(output_df.loc[output_df["Mill"] == mill, "Status"].values[0])
        if mill == "MILL-F":
            adj_bias = 0 if mill_status_str == "RUNNING" or mill_status_str == "STOP" else -5
        else:
            adj_bias = 0 if adj_val > 0.4 else -5


        spray_b = get_spray_bias(mill, spray_dev)
        metal_b = get_metal_bias(mill, metal_dev)
        gcv_b   = get_gcv_bias(mill, gcv_dev)
        load_b  = get_load_bias(mill, load_dev)
        aph_b   = aph_bias

        eff_hi = min(round(
            hi + spray_b + metal_b + aph_b + gcv_b + adj_bias + load_b, 2
        ), 99)

        sched.append({
            "Mill":         mill,
            "Health Index": hi,
            "STATUS":       status,
            "PRIORITY":     0,
            "Spray_Bias":   spray_b,
            "Metal_Bias":   metal_b,
            "APH_Bias":     aph_b,
            "GCV_Bias":     gcv_b,
            "AdjMil_Bias":  adj_bias,
            "Load_Bias":    load_b,
            "Eff_HI":       eff_hi,
            "Eff_Rank":     0,
            "Run/Stop":     "STOP"  # default; overwritten below
        })

    priority_idx = sorted(
        [i for i, s in enumerate(sched) if s["STATUS"] in ("Available", "Standby")],
        key=lambda i: sched[i]["Health Index"],
        reverse=True
    )
    for rank, idx in enumerate(priority_idx, 1):
        sched[idx]["PRIORITY"] = rank

    avail_idx = sorted(
        [i for i, s in enumerate(sched) if s["STATUS"] == "Available"],
        key=lambda i: sched[i]["Eff_HI"],
        reverse=True
    )
    for rank, idx in enumerate(avail_idx, 1):
        sched[idx]["Eff_Rank"] = rank
        sched[idx]["Run/Stop"] = get_run_stop_status(
            mill_status=sched[idx]["STATUS"],
            mills_required=mills_required,
            mill_priority=rank
        )

    sched_df = pd.DataFrame(sched)

    def color_run_stop(val):
        if val == "RUN":     return "color:green;font-weight:bold"
        if val == "STANDBY": return "color:orange;font-weight:bold"
        return "color:red;font-weight:bold"

    st.dataframe(
        sched_df.style.map(color_run_stop, subset=["Run/Stop"]),
        use_container_width=True
    )

    with st.expander("View Risk Penalty Factors"):
        rp_df = pd.DataFrame([
            {"Parameter": "SUPER HEATER SPRAY",          "Design": spray_design, "Operating": spray_op,
             "Deviation %": round(spray_dev, 1), "Bias": "per-mill"},
            {"Parameter": "HIGHEST METAL TEMPERATURE",   "Design": metal_design, "Operating": metal_op,
             "Deviation %": round(metal_dev, 1), "Bias": "per-mill"},
            {"Parameter": "APH INLET FLUE GAS TEMP",     "Design": aph_design,   "Operating": aph_op,
             "Deviation %": round(aph_dev, 1),   "Bias": aph_bias},
            {"Parameter": "GROSS CALORIFIC VALUE (GCV)", "Design": gcv_design,   "Operating": gcv_op,
             "Deviation %": round(gcv_dev, 1),   "Bias": "per-mill"},
            {"Parameter": "LOAD",                        "Design": load_design,  "Operating": load_op,
             "Deviation %": round(load_dev, 1),  "Bias": "per-mill"},
            {"Parameter": "EXPECTED COAL FLOW",          "Design": "-",          "Operating": round(expected_coal_flow, 2),
             "Deviation %": "-",                         "Bias": f"{mills_required} mills"},
        ])
        st.dataframe(rp_df, use_container_width=True)

    st.subheader("Scheduling Summary")
    run_mills = sched_df[sched_df["Run/Stop"] == "RUN"]["Mill"].tolist()
    st.info(f"Mills required to run: **{mills_required}**")
    st.success(f"✅ Mills scheduled to RUN: {', '.join(run_mills)}")

    # -------------------------------------------------------
    # 6. MILL SCHEDULING RANKING VISUALIZATION
    # -------------------------------------------------------
    st.header("5. MILL SCHEDULING RANKING VISUALIZATION")

    viz_df = sched_df[sched_df["STATUS"].isin(["Available", "Standby", "Emergency"])].sort_values("Eff_HI", ascending=False).reset_index(drop=True)

    def bar_color(row):
        if row["Run/Stop"] == "RUN":
            return "#2ecc71" if row["Eff_HI"] >= 80 else "#f39c12"
        return "#e74c3c"

    colors = [bar_color(r) for _, r in viz_df.iterrows()]
    labels = [f"{r['Run/Stop']} | Rank {int(r['Eff_Rank'])}" for _, r in viz_df.iterrows()]

    bar_fig = go.Figure(go.Bar(
        x=viz_df["Eff_HI"],
        y=viz_df["Mill"],
        orientation="h",
        marker_color=colors,
        text=[f"{v:.1f}" for v in viz_df["Eff_HI"]],
        textposition="outside",
        customdata=labels,
        hovertemplate="%{y}: %{x:.1f} — %{customdata}<extra></extra>"
    ))
    bar_fig.add_vline(x=60, line_dash="dash", line_color="red",   annotation_text="60 (Min)", annotation_position="top")
    bar_fig.add_vline(x=80, line_dash="dash", line_color="green", annotation_text="80 (Good)", annotation_position="top")
    bar_fig.update_layout(
        title="Effective Health Index — Mill Ranking",
        xaxis=dict(title="Effective HI", range=[0, 110]),
        yaxis=dict(autorange="reversed"),
        height=320, margin=dict(l=20, r=40, t=50, b=30)
    )
    st.plotly_chart(bar_fig, use_container_width=True)

    # Gauge charts
    gauge_cols = st.columns(len(MILLS))
    for j, mill in enumerate(MILLS):
        row = sched_df[sched_df["Mill"] == mill].iloc[0]
        val = row["Eff_HI"]
        decision = row["Run/Stop"] if row["STATUS"] != "Not Available" else "N/A"
        needle_color = "#2ecc71" if val >= 80 else ("#f39c12" if val >= 60 else "#e74c3c")
        g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=val,
            title={"text": f"{mill}<br><span style='font-size:12px'>{decision}</span>", "font": {"size": 13}},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": needle_color},
                "steps": [
                    {"range": [0,  60], "color": "#fadbd8"},
                    {"range": [60, 80], "color": "#fdebd0"},
                    {"range": [80, 100], "color": "#d5f5e3"},
                ],
                "threshold": {"line": {"color": "black", "width": 2}, "thickness": 0.75, "value": val}
            }
        ))
        g.update_layout(height=200, margin=dict(l=10, r=10, t=40, b=10))
        gauge_cols[j].plotly_chart(g, use_container_width=True)

    # Ranked priority table with inline progress bars
    st.subheader("Priority Ranking Table")
    ranked = sched_df.copy()
    ranked["_sort"] = ranked["Eff_Rank"].apply(lambda x: x if x > 0 else 999)
    ranked = ranked.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)

    rows_html = ""
    for _, r in ranked.iterrows():
        rank_str = str(int(r["Eff_Rank"])) if r["Eff_Rank"] > 0 else "—"
        decision = r["Run/Stop"] if r["STATUS"] != "Not Available" else "NOT AVAILABLE"
        dec_color = "#2ecc71" if decision == "RUN" else ("#f39c12" if decision == "STANDBY" else ("#e74c3c" if decision == "STOP" else "#95a5a6"))
        bar_w = int(r["Eff_HI"]) if r["Eff_HI"] > 0 else 0
        bar_c = "#2ecc71" if r["Eff_HI"] >= 80 else ("#f39c12" if r["Eff_HI"] >= 60 else "#e74c3c")
        rows_html += f"""
        <tr>
          <td style='text-align:center;font-weight:bold;font-size:18px'>{rank_str}</td>
          <td style='font-weight:bold'>{r['Mill']}</td>
          <td>{r['Health Index']:.1f}</td>
          <td>
            <div style='background:#eee;border-radius:4px;width:100%;height:16px'>
              <div style='background:{bar_c};width:{bar_w}%;height:16px;border-radius:4px'></div>
            </div>
            <span style='font-size:11px'>{r['Eff_HI']:.1f}</span>
          </td>
          <td style='color:{dec_color};font-weight:bold;text-align:center'>{decision}</td>
        </tr>"""

    table_html = f"""
    <table style='width:100%;border-collapse:collapse;font-family:sans-serif'>
      <thead><tr style='background:#2c3e50;color:white'>
        <th style='padding:8px'>Rank</th>
        <th style='padding:8px'>Mill</th>
        <th style='padding:8px'>HI</th>
        <th style='padding:8px'>Effective HI</th>
        <th style='padding:8px'>Decision</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""
    st.markdown(table_html, unsafe_allow_html=True)
