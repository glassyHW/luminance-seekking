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

# ================== 全局常量 ==================
STAGE_OPTIONS = ["EVT", "DVT", "PVT", "MP"]
MODE_OPTIONS = [
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
    """缓存 spreadsheet 对象，避免重复打开"""
    client = get_gs_client()
    return client.open_by_key(SPREADSHEET_ID)

def get_worksheet(sheet_title):
    sh = get_spreadsheet()
    return sh.worksheet(sheet_title)

def ensure_worksheet_exists(sheet_title, headers):
    """确保工作表存在，并且拥有正确的表头（不存在则创建）"""
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_title)
        # 检查是否为空（没有数据也没有表头）
        if not ws.get_all_values():
            ws.update([headers])
        return ws
    except gspread.exceptions.WorksheetNotFound:
        # 创建新工作表
        ws = sh.add_worksheet(title=sheet_title, rows=1, cols=len(headers))
        ws.update([headers])
        return ws

def load_data_from_sheet(worksheet_name):
    """从工作表读取数据"""
    try:
        ws = get_worksheet(worksheet_name)
        records = ws.get_all_records()
        df = pd.DataFrame(records)
        for col in COMMON_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').round(5)
        return df
    except Exception:
        return pd.DataFrame()

def save_data_to_sheet(df, worksheet_name, max_retries=3):
    """带重试的保存操作，应对限流"""
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

# ================== 业务函数 ==================
def init_sheets():
    """初始化三个工作表（仅在首次访问时真正执行）"""
    # 定义三个工作表的表头
    actual_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + ACTUAL_EXTRA_FIELDS
    theory_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS
    optics_headers = OPTICS_FIELDS

    # 一次性保证所有工作表存在
    ensure_worksheet_exists(WORKSHEET_ACTUAL, actual_headers)
    ensure_worksheet_exists(WORKSHEET_THEORY, theory_headers)
    ensure_worksheet_exists(WORKSHEET_OPTICS, optics_headers)

# 其他数据读写函数保持不变，但内部调用 load_data_from_sheet / save_data_to_sheet
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

# ================== Session 初始化 ==================
def init_session_state():
    if 'filter_groups' not in st.session_state:
        st.session_state.filter_groups = [{'id': 0}]
    if 'actual_authenticated' not in st.session_state:
        st.session_state.actual_authenticated = False
    if 'theory_authenticated' not in st.session_state:
        st.session_state.theory_authenticated = False

# ================== 主程序 UI ==================
def main():
    st.set_page_config(layout="wide", page_title="光学数据管理系统")
    st.title("📊 光学数据管理系统")
    init_session_state()

    # 只在第一次运行或需要时初始化工作表（因为使用了缓存，不会重复请求）
    # 但 init_sheets 内部会调用 ensure_worksheet_exists，而 ensure_worksheet_exists 内部会调用 get_worksheet
    # 依然会发起请求，不过因为 @st.cache_resource 缓存了 spreadsheet，所以每个工作表只会创建一次。
    # 如果已经创建过，后续调用只是检查是否存在，开销较小（但仍然有一次 get_all_values 请求）。
    # 为了进一步减少请求，我们可以用一个 session_state 标记是否已经初始化过。
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
            with st.form(key='actual_form', clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS)
                with col3:
                    input_mode = st.selectbox("模式", MODE_OPTIONS)
                with col4:
                    input_source = st.selectbox("数据来源", ["研发测试", "产线测试", "认证机构"])

                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values = {}
                for i, field in enumerate(COMMON_FIELDS):
                    with cols[i]:
                        default_val = 0.0
                        if field == "亮度":
                            default_val = 100.0
                        elif field == "色点x":
                            default_val = 0.26
                        elif field == "色点y":
                            default_val = 0.27
                        elif field == "色温":
                            default_val = 6500.0
                        elif field == "Duv":
                            default_val = 0.003
                        elif field == "SSI":
                            default_val = 85.0
                        elif field == "灯温":
                            default_val = 6500.0
                        elif field == "duty":
                            default_val = 50.0
                        elif field == "对比度":
                            default_val = 1000.0
                        elif field == "色域":
                            default_val = 100.0
                        input_values[field] = st.number_input(field, value=default_val, format="%.5f", step=0.00001)

                st.subheader("3. 附加信息")
                extra_cols = st.columns(len(ACTUAL_EXTRA_FIELDS))
                input_extras = {}
                for i, field in enumerate(ACTUAL_EXTRA_FIELDS):
                    with extra_cols[i]:
                        input_extras[field] = st.text_input(field)

                if st.form_submit_button("保存实测数据"):
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": input_mode,
                        "数据来源": input_source,
                        "实测/理论": "实测",
                        **input_values,
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
                display_df = df_actual.copy()
                for col in COMMON_FIELDS:
                    if col in display_df:
                        display_df[col] = display_df[col].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "")
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_actual", use_container_width=True)
                if st.button("💾 保存实测表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = pd.to_numeric(edited[col], errors='coerce')
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
            with st.form(key='theory_form', clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞", key="t_model")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS, key="t_stage")
                with col3:
                    input_mode = st.selectbox("模式", MODE_OPTIONS, key="t_mode")
                st.info("📌 理论数据的数据来源固定为：理论评估")

                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values = {}
                for i, field in enumerate(COMMON_FIELDS):
                    with cols[i]:
                        default_val = 0.0
                        if field == "亮度":
                            default_val = 100.0
                        elif field == "色点x":
                            default_val = 0.26
                        elif field == "色点y":
                            default_val = 0.27
                        elif field == "色温":
                            default_val = 6500.0
                        elif field == "Duv":
                            default_val = 0.003
                        elif field == "SSI":
                            default_val = 85.0
                        elif field == "灯温":
                            default_val = 6500.0
                        elif field == "duty":
                            default_val = 50.0
                        elif field == "对比度":
                            default_val = 1000.0
                        elif field == "色域":
                            default_val = 100.0
                        input_values[field] = st.number_input(field, value=default_val, format="%.5f", step=0.00001, key=f"t_{field}")

                if st.form_submit_button("保存理论数据"):
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": input_mode,
                        "数据来源": "理论评估",
                        "实测/理论": "理论",
                        **input_values
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
                display_df = df_theory.copy()
                for col in COMMON_FIELDS:
                    if col in display_df:
                        display_df[col] = display_df[col].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "")
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_theory", use_container_width=True)
                if st.button("💾 保存理论表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = pd.to_numeric(edited[col], errors='coerce')
                    edited['数据来源'] = '理论评估'
                    save_theory_data(edited)
                    st.success("理论历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无理论历史数据")

    # ---------------------------------- 数据分析（无密码） ----------------------------------
    with tab3:
        st.header("数据查询与分析")
        with st.expander("筛选条件", expanded=True):
            if st.button("+ 添加筛选组"):
                st.session_state.filter_groups.append({'id': len(st.session_state.filter_groups)})
                st.rerun()
            all_filters = []
            for i, g in enumerate(st.session_state.filter_groups):
                st.markdown(f"**筛选组 {i+1}**")
                cols = st.columns([2,1,1,2,1])
                with cols[0]:
                    f_model = st.text_input("机型", key=f"model_{i}")
                with cols[1]:
                    f_stage = st.selectbox("阶段", ["全部"]+STAGE_OPTIONS, key=f"stage_{i}")
                with cols[2]:
                    f_mode = st.selectbox("模式", ["全部"]+MODE_OPTIONS, key=f"mode_{i}")
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
                    display = final.copy()
                    for col in COMMON_FIELDS:
                        if col in display:
                            display[col] = display[col].apply(lambda x: f"{float(x):.5f}" if pd.notna(x) else "")
                    st.dataframe(display, use_container_width=True)

    # ---------------------------------- 光机信息（无密码） ----------------------------------
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
