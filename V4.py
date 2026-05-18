import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime

# ================== Google Sheets 配置 ==================
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SPREADSHEET_ID = '1JW1fQRYMts20yc4ctV8aZYzyhbb6wmLhEhMSH1EtIUU'
WORKSHEET_ACTUAL = '实测数据'
WORKSHEET_THEORY = '理论数据'
WORKSHEET_OPTICS = '光机信息'
WORKSHEET_MODES = '模式配置'

# ================== 全局常量 ==================
STAGE_OPTIONS = ["EVT", "DVT", "PVT", "MP"]
DEFAULT_MODE_OPTIONS = [
    "三段AI", "三段运动", "三段filmmaker", "三段电影",
    "五段AI", "五段filmmaker", "五段电影",
    "性能", "overlap"
]
SOURCE_OPTIONS = ["研发测试", "产线测试", "认证机构", "理论评估"]
COMMON_FIELDS = ["亮度", "色点x", "色点y", "色温", "Duv", "SSI", "灯温", "duty", "对比度", "色域"]
ACTUAL_EXTRA_FIELDS = ["照度计编号", "整机SN", "版本-固件", "版本-image"]
OPTICS_FIELDS = ["机型", "DMD型号", "灯的型号（颗数）", "风扇型号", "DMD温度（包含余量）", "记录时间"]
ACTUAL_PASSWORD = "Aa123456"
THEORY_PASSWORD = "Aa654321"

# ================== 带缓存的 Google Sheets 客户端 ==================
@st.cache_resource
def get_gs_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    return gspread.authorize(creds)

@st.cache_resource
def get_spreadsheet():
    client = get_gs_client()
    return client.open_by_key(SPREADSHEET_ID)

def get_worksheet(sheet_title):
    sh = get_spreadsheet()
    return sh.worksheet(sheet_title)

def ensure_worksheet_exists(sheet_title, headers):
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_title)
        if not ws.get_all_values():
            ws.update([headers])
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_title, rows=1, cols=len(headers))
        ws.update([headers])
        return ws

def load_data_from_sheet(worksheet_name):
    try:
        ws = get_worksheet(worksheet_name)
        records = ws.get_all_records()
        df = pd.DataFrame(records)
        for col in COMMON_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='ignore')
        return df
    except Exception:
        return pd.DataFrame()

def save_data_to_sheet(df, worksheet_name, max_retries=3):
    for attempt in range(max_retries):
        try:
            ws = get_worksheet(worksheet_name)
            ws.clear()
            if not df.empty:
                df_clean = df.where(pd.notnull(df), None)
                ws.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
            else:
                ws.update([df.columns.tolist()])
            return
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 2 ** attempt
                st.warning(f"触发 API 限流，等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                raise

# ================== 模式配置管理 ==================
@st.cache_data(ttl=60)
def load_mode_options():
    try:
        ws = get_worksheet(WORKSHEET_MODES)
        records = ws.get_all_records()
        if records:
            modes = [r['模式'] for r in records if r.get('模式')]
            return modes if modes else DEFAULT_MODE_OPTIONS.copy()
        else:
            ws.update([['模式']] + [[m] for m in DEFAULT_MODE_OPTIONS])
            return DEFAULT_MODE_OPTIONS.copy()
    except gspread.exceptions.WorksheetNotFound:
        sh = get_spreadsheet()
        ws = sh.add_worksheet(title=WORKSHEET_MODES, rows=1, cols=1)
        ws.update([['模式']] + [[m] for m in DEFAULT_MODE_OPTIONS])
        return DEFAULT_MODE_OPTIONS.copy()

def add_new_mode(mode_name):
    if not mode_name or mode_name.strip() == "":
        return False
    mode_name = mode_name.strip()
    existing = load_mode_options()
    if mode_name in existing:
        return False
    ws = get_worksheet(WORKSHEET_MODES)
    ws.append_row([mode_name])
    st.cache_data.clear()
    return True

# ================== 业务函数 ==================
def init_sheets():
    actual_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + ACTUAL_EXTRA_FIELDS
    theory_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS
    optics_headers = OPTICS_FIELDS
    ensure_worksheet_exists(WORKSHEET_ACTUAL, actual_headers)
    ensure_worksheet_exists(WORKSHEET_THEORY, theory_headers)
    ensure_worksheet_exists(WORKSHEET_OPTICS, optics_headers)
    load_mode_options()

def load_actual_data():
    return load_data_from_sheet(WORKSHEET_ACTUAL)

def save_actual_data(df):
    save_data_to_sheet(df, WORKSHEET_ACTUAL)

def load_theory_data():
    return load_data_from_sheet(WORKSHEET_THEORY)

def save_theory_data(df):
    save_data_to_sheet(df, WORKSHEET_THEORY)

def load_optics_data():
    return load_data_from_sheet(WORKSHEET_OPTICS)

def save_optics_data(df):
    save_data_to_sheet(df, WORKSHEET_OPTICS)

def get_data_with_source():
    df_actual = load_actual_data()
    if not df_actual.empty:
        df_actual['实测/理论'] = '实测'
    df_theory = load_theory_data()
    if not df_theory.empty:
        df_theory['实测/理论'] = '理论'
    df_all = pd.concat([df_actual, df_theory], ignore_index=True, sort=False)
    df_all = df_all.fillna("")
    return df_all

def safe_float_convert(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return round(float(value), 5)
    except ValueError:
        return str(value)

def format_dataframe_for_display(df, fields):
    df_display = df.copy()
    for col in fields:
        if col in df_display.columns and pd.api.types.is_numeric_dtype(df_display[col]):
            df_display[col] = df_display[col].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "")
    return df_display

# ================== Session 初始化 ==================
def init_session_state():
    if 'filter_groups' not in st.session_state:
        st.session_state.filter_groups = [{'id': 0}]
    if 'actual_authenticated' not in st.session_state:
        st.session_state.actual_authenticated = False
    if 'theory_authenticated' not in st.session_state:
        st.session_state.theory_authenticated = False
    if 'selected_mode_actual' not in st.session_state:
        st.session_state.selected_mode_actual = DEFAULT_MODE_OPTIONS[0]
    if 'selected_mode_theory' not in st.session_state:
        st.session_state.selected_mode_theory = DEFAULT_MODE_OPTIONS[0]
    if 'show_add_mode_actual' not in st.session_state:
        st.session_state.show_add_mode_actual = False
    if 'show_add_mode_theory' not in st.session_state:
        st.session_state.show_add_mode_theory = False

# ================== 主程序 UI ==================
def main():
    st.set_page_config(layout="wide", page_title="光学数据管理系统")
    st.title("📊 光学数据管理系统")
    init_session_state()

    if 'sheets_initialized' not in st.session_state:
        with st.spinner("正在检查/初始化工作表..."):
            init_sheets()
            st.session_state.sheets_initialized = True

    tab1, tab2, tab3, tab4 = st.tabs(["【录入】实测数据", "【录入】理论数据", "【查询】数据分析", "【查询】光机信息"])

    # ---------------------------------- 实测数据 ----------------------------------
    with tab1:
        st.header("实测数据录入")
        if not st.session_state.actual_authenticated:
            st.warning("请输入密码以查看和操作实测数据")
            with st.form("actual_auth_form"):
                pwd = st.text_input("密码", type="password")
                if st.form_submit_button("验证"):
                    if pwd == ACTUAL_PASSWORD:
                        st.session_state.actual_authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            # ---- 模式选择器（在表单外部）----
            col_mode, col_add = st.columns([3, 1])
            with col_mode:
                mode_options = load_mode_options()
                selected_mode = st.selectbox(
                    "模式", mode_options,
                    key="actual_mode_select",
                    index=mode_options.index(st.session_state.selected_mode_actual) if st.session_state.selected_mode_actual in mode_options else 0
                )
                st.session_state.selected_mode_actual = selected_mode
            with col_add:
                if st.button("➕ 新增模式", key="actual_add_mode_btn"):
                    st.session_state.show_add_mode_actual = True
            if st.session_state.show_add_mode_actual:
                with st.popover("新增模式", use_container_width=True):
                    new_mode = st.text_input("新模式名称", key="actual_new_mode_input")
                    if st.button("确定添加", key="actual_confirm_add"):
                        if new_mode and new_mode.strip():
                            if add_new_mode(new_mode.strip()):
                                st.success(f"模式「{new_mode.strip()}」已添加")
                                st.session_state.show_add_mode_actual = False
                                st.rerun()
                            else:
                                st.error("模式已存在或添加失败")
                        else:
                            st.warning("请输入模式名称")
                    if st.button("取消", key="actual_cancel_add"):
                        st.session_state.show_add_mode_actual = False
                        st.rerun()

            # ---- 数据录入表单 ----
            with st.form(key='actual_form', clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS)
                with col3:
                    # 只读显示当前选中的模式（不可编辑）
                    st.text_input("模式", value=st.session_state.selected_mode_actual, disabled=True)
                with col4:
                    input_source = st.selectbox("数据来源", ["研发测试", "产线测试", "认证机构"])

                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values = {}
                for i, field in enumerate(COMMON_FIELDS):
                    with cols[i]:
                        input_values[field] = st.text_input(field, value="", key=f"actual_{field}",
                                                            placeholder="留空或填入数字/文字")

                st.subheader("3. 附加信息")
                extra_cols = st.columns(len(ACTUAL_EXTRA_FIELDS))
                input_extras = {}
                for i, field in enumerate(ACTUAL_EXTRA_FIELDS):
                    with extra_cols[i]:
                        input_extras[field] = st.text_input(field)

                if st.form_submit_button("保存实测数据"):
                    converted = {f: safe_float_convert(input_values[f]) for f in COMMON_FIELDS}
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": st.session_state.selected_mode_actual,
                        "数据来源": input_source,
                        "实测/理论": "实测",
                        **converted,
                        **input_extras
                    }
                    df = load_actual_data()
                    if df.empty:
                        df = pd.DataFrame([new_row])
                    else:
                        for k in new_row:
                            if k not in df.columns:
                                df[k] = ""
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    save_actual_data(df)
                    st.success("✅ 实测数据保存成功！")
                    st.rerun()

            st.markdown("---")
            st.subheader("📜 实测历史数据管理")
            df_actual = load_actual_data()
            if not df_actual.empty:
                display_df = format_dataframe_for_display(df_actual, COMMON_FIELDS)
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_actual", use_container_width=True)
                if st.button("💾 保存实测表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = edited[col].apply(lambda x: safe_float_convert(x) if isinstance(x, str) else x)
                    save_actual_data(edited)
                    st.success("实测历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无实测历史数据")

    # ---------------------------------- 理论数据 ----------------------------------
    with tab2:
        st.header("理论数据录入")
        if not st.session_state.theory_authenticated:
            st.warning("请输入密码以查看和操作理论数据")
            with st.form("theory_auth_form"):
                pwd = st.text_input("密码", type="password")
                if st.form_submit_button("验证"):
                    if pwd == THEORY_PASSWORD:
                        st.session_state.theory_authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            # ---- 模式选择器（在表单外部）----
            col_mode, col_add = st.columns([3, 1])
            with col_mode:
                mode_options = load_mode_options()
                selected_mode = st.selectbox(
                    "模式", mode_options,
                    key="theory_mode_select",
                    index=mode_options.index(st.session_state.selected_mode_theory) if st.session_state.selected_mode_theory in mode_options else 0
                )
                st.session_state.selected_mode_theory = selected_mode
            with col_add:
                if st.button("➕ 新增模式", key="theory_add_mode_btn"):
                    st.session_state.show_add_mode_theory = True
            if st.session_state.show_add_mode_theory:
                with st.popover("新增模式", use_container_width=True):
                    new_mode = st.text_input("新模式名称", key="theory_new_mode_input")
                    if st.button("确定添加", key="theory_confirm_add"):
                        if new_mode and new_mode.strip():
                            if add_new_mode(new_mode.strip()):
                                st.success(f"模式「{new_mode.strip()}」已添加")
                                st.session_state.show_add_mode_theory = False
                                st.rerun()
                            else:
                                st.error("模式已存在或添加失败")
                        else:
                            st.warning("请输入模式名称")
                    if st.button("取消", key="theory_cancel_add"):
                        st.session_state.show_add_mode_theory = False
                        st.rerun()

            # ---- 数据录入表单 ----
            with st.form(key='theory_form', clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞", key="t_model")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS, key="t_stage")
                with col3:
                    st.text_input("模式", value=st.session_state.selected_mode_theory, disabled=True)
                st.info("📌 理论数据的数据来源固定为：理论评估")

                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values = {}
                for i, field in enumerate(COMMON_FIELDS):
                    with cols[i]:
                        input_values[field] = st.text_input(field, value="", key=f"theory_{field}",
                                                            placeholder="留空或填入数字/文字")

                if st.form_submit_button("保存理论数据"):
                    converted = {f: safe_float_convert(input_values[f]) for f in COMMON_FIELDS}
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": st.session_state.selected_mode_theory,
                        "数据来源": "理论评估",
                        "实测/理论": "理论",
                        **converted
                    }
                    for f in ACTUAL_EXTRA_FIELDS:
                        new_row[f] = ""
                    df = load_theory_data()
                    if df.empty:
                        df = pd.DataFrame([new_row])
                    else:
                        for k in new_row:
                            if k not in df.columns:
                                df[k] = ""
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    save_theory_data(df)
                    st.success("✅ 理论数据保存成功！")
                    st.rerun()

            st.markdown("---")
            st.subheader("📜 理论历史数据管理")
            df_theory = load_theory_data()
            if not df_theory.empty:
                display_df = format_dataframe_for_display(df_theory, COMMON_FIELDS)
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_theory", use_container_width=True)
                if st.button("💾 保存理论表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = edited[col].apply(lambda x: safe_float_convert(x) if isinstance(x, str) else x)
                    edited['数据来源'] = '理论评估'
                    save_theory_data(edited)
                    st.success("理论历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无理论历史数据")

    # ---------------------------------- 数据分析 ----------------------------------
    with tab3:
        st.header("数据查询与分析")
        with st.expander("筛选条件", expanded=True):
            if st.button("+ 添加筛选组"):
                st.session_state.filter_groups.append({'id': len(st.session_state.filter_groups)})
                st.rerun()
            all_filters = []
            dynamic_mode_options = ["全部"] + load_mode_options()
            for i, g in enumerate(st.session_state.filter_groups):
                st.markdown(f"**筛选组 {i+1}**")
                cols = st.columns([2,1,1,2,1])
                with cols[0]:
                    f_model = st.text_input("机型", key=f"model_{i}")
                with cols[1]:
                    f_stage = st.selectbox("阶段", ["全部"]+STAGE_OPTIONS, key=f"stage_{i}")
                with cols[2]:
                    f_mode = st.selectbox("模式", dynamic_mode_options, key=f"mode_{i}")
                with cols[3]:
                    f_source = st.selectbox("数据来源", ["全部"]+SOURCE_OPTIONS, key=f"source_{i}")
                with cols[4]:
                    if st.button("删除", key=f"del_{i}"):
                        st.session_state.filter_groups.pop(i)
                        st.rerun()
                all_filters.append({"model":f_model, "stage":f_stage, "mode":f_mode, "source":f_source})
        if st.button("执行查询", type="primary"):
            df_all = get_data_with_source()
            if df_all.empty:
                st.warning("暂无任何数据")
            else:
                final = pd.DataFrame()
                for f in all_filters:
                    mask = pd.Series([True]*len(df_all))
                    if f['model']:
                        mask &= df_all['机型'].str.contains(f['model'], case=False, na=False)
                    if f['stage'] != "全部":
                        mask &= df_all['阶段'] == f['stage']
                    if f['mode'] != "全部":
                        mask &= df_all['模式'] == f['mode']
                    if f['source'] != "全部":
                        mask &= df_all['数据来源'] == f['source']
                    final = pd.concat([final, df_all[mask]])
                final.drop_duplicates(inplace=True)
                if final.empty:
                    st.info("未找到符合条件的数据")
                else:
                    st.success(f"查询结果 (共 {len(final)} 条)")
                    display = format_dataframe_for_display(final, COMMON_FIELDS)
                    st.dataframe(display, use_container_width=True)

    # ---------------------------------- 光机信息 ----------------------------------
    with tab4:
        st.header("光机信息查询")
        st.markdown("此表格用于记录各机型的光机相关信息，支持添加、编辑、删除操作。")
        df_optics = load_optics_data()
        edited = st.data_editor(
            df_optics,
            num_rows="dynamic",
            use_container_width=True,
            key="optics_editor",
            column_config={
                "机型": st.column_config.TextColumn("机型", required=True),
                "DMD型号": st.column_config.TextColumn("DMD型号"),
                "灯的型号（颗数）": st.column_config.TextColumn("灯的型号（颗数）", help="例如：LED 3颗"),
                "风扇型号": st.column_config.TextColumn("风扇型号"),
                "DMD温度（包含余量）": st.column_config.TextColumn("DMD温度（包含余量）", help="例如：60°C (余量5°C)"),
                "记录时间": st.column_config.TextColumn("记录时间", help="格式建议：YYYY-MM-DD HH:MM"),
            }
        )
        if st.button("💾 保存光机信息"):
            save_optics_data(edited)
            st.success("光机信息已保存！")
            st.rerun()
        st.caption("提示：在表格最后一行下方点击“+”可添加新行，勾选行前面的复选框后点击上方出现的“删除”按钮可删除行。")

if __name__ == "__main__":
    main()
