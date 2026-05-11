# --- V4.3把数据从github迁移到google
import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# ================== Google Sheets 配置 ==================
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# ⭐ 使用 Spreadsheet ID 而不是文件名（更稳定）
SPREADSHEET_ID = '1JW1fQRYMts20yc4ctV8aZYzyhbb6wmLhEhMSH1EtIUU'   # 你的表格ID

# 工作表名称（三个标签页的名字）
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

# 密码
ACTUAL_PASSWORD = "Aa123456"
THEORY_PASSWORD = "Aa654321"

# ================== Google Sheets 交互函数 ==================
@st.cache_resource
def get_gs_client():
    """获取 Google Sheets 客户端（单例）"""
    # 从 secrets 中读取完整的 JSON 字符串
    json_str = st.secrets["gcp_service_account_json"]
    creds_dict = json.loads(json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    return gspread.authorize(creds)

def get_worksheet(sheet_title):
    """获取工作表对象（通过 Spreadsheet ID）"""
    client = get_gs_client()
    sh = client.open_by_key(SPREADSHEET_ID)   # 关键修改：使用 ID 打开
    return sh.worksheet(sheet_title)

def load_data_from_sheet(worksheet_name):
    """从工作表读取数据为 DataFrame"""
    try:
        ws = get_worksheet(worksheet_name)
        records = ws.get_all_records()
        df = pd.DataFrame(records)
        # 数值列转换
        for col in COMMON_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').round(5)
        return df
    except Exception as e:
        return pd.DataFrame()

def save_data_to_sheet(df, worksheet_name):
    """将 DataFrame 完全覆盖写入工作表"""
    ws = get_worksheet(worksheet_name)
    ws.clear()
    if not df.empty:
        ws.update([df.columns.values.tolist()] + df.values.tolist())
    else:
        ws.update([df.columns.tolist()])

def init_sheets():
    """确保三个工作表存在且至少包含列头"""
    actual_columns = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + ACTUAL_EXTRA_FIELDS
    theory_columns = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS
    optics_columns = OPTICS_FIELDS

    for ws_name, cols in [(WORKSHEET_ACTUAL, actual_columns),
                          (WORKSHEET_THEORY, theory_columns),
                          (WORKSHEET_OPTICS, optics_columns)]:
        try:
            ws = get_worksheet(ws_name)
            if not ws.get_all_values():
                ws.update([cols])
        except gspread.exceptions.WorksheetNotFound:
            # 工作表不存在，创建
            client = get_gs_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            sh.add_worksheet(title=ws_name, rows=1, cols=len(cols))
            ws = sh.worksheet(ws_name)
            ws.update([cols])

# ================== 业务数据函数 ==================
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
    """合并实测和理论数据用于查询"""
    df_actual = load_actual_data()
    if not df_actual.empty:
        df_actual['实测/理论'] = '实测'
    df_theory = load_theory_data()
    if not df_theory.empty:
        df_theory['实测/理论'] = '理论'
    df_all = pd.concat([df_actual, df_theory], ignore_index=True, sort=False)
    df_all = df_all.fillna("")
    return df_all

# ================== Session 状态初始化 ==================
def init_session_state():
    if 'filter_groups' not in st.session_state:
        st.session_state.filter_groups = [{'id': 0}]
    if 'actual_authenticated' not in st.session_state:
        st.session_state.actual_authenticated = False
    if 'theory_authenticated' not in st.session_state:
        st.session_state.theory_authenticated = False

# ================== 主程序 ==================
def main():
    st.set_page_config(layout="wide", page_title="光学数据管理系统")
    st.title("📊 光学数据管理系统")
    init_session_state()
    init_sheets()   # 确保工作表存在

    tab1, tab2, tab3, tab4 = st.tabs(["【录入】实测数据", "【录入】理论数据", "【查询】数据分析", "【查询】光机信息"])

    # ---------- 实测数据 ----------
    with tab1:
        st.header("实测数据录入")
        if not st.session_state.actual_authenticated:
            st.warning("请输入密码以查看和操作实测数据")
            with st.form("actual_auth_form"):
                pwd = st.text_input("密码", type="password")
                submit = st.form_submit_button("验证")
                if submit:
                    if pwd == ACTUAL_PASSWORD:
                        st.session_state.actual_authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            # 录入表单
            with st.form(key='actual_form', clear_on_submit=True):
                st.subheader("1. 基础信息")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS, index=0)
                with col3:
                    input_mode = st.selectbox("模式", MODE_OPTIONS, index=0)
                with col4:
                    input_source = st.selectbox("数据来源", ["研发测试", "产线测试", "认证机构"], index=0)

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
                cols_extra = st.columns(len(ACTUAL_EXTRA_FIELDS))
                input_extras = {}
                for i, field in enumerate(ACTUAL_EXTRA_FIELDS):
                    with cols_extra[i]:
                        input_extras[field] = st.text_input(field)

                submitted = st.form_submit_button("保存实测数据")
                if submitted:
                    new_data = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": input_mode,
                        "数据来源": input_source,
                        "实测/理论": "实测",
                    }
                    new_data.update(input_values)
                    new_data.update(input_extras)
                    df = load_actual_data()
                    if df.empty:
                        df = pd.DataFrame([new_data])
                    else:
                        for k in new_data.keys():
                            if k not in df.columns:
                                df[k] = ""
                        df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                    save_actual_data(df)
                    st.success("✅ 实测数据保存成功！")
                    st.rerun()

            st.markdown("---")
            st.subheader("📜 实测历史数据管理")
            df_actual = load_actual_data()
            if not df_actual.empty:
                if '数据来源' not in df_actual.columns:
                    df_actual['数据来源'] = '研发测试'
                display_df = df_actual.copy()
                for col in COMMON_FIELDS:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].apply(lambda x: f'{x:.5f}' if pd.notna(x) and x != '' else x)
                edited_df = st.data_editor(display_df, num_rows="dynamic", key="editor_actual", use_container_width=True)
                if st.button("💾 保存实测表格修改", key="save_actual_edit"):
                    for col in COMMON_FIELDS:
                        if col in edited_df.columns:
                            edited_df[col] = pd.to_numeric(edited_df[col], errors='coerce')
                    save_actual_data(edited_df)
                    st.success("实测历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无实测历史数据")

    # ---------- 理论数据 ----------
    with tab2:
        st.header("理论数据录入")
        if not st.session_state.theory_authenticated:
            st.warning("请输入密码以查看和操作理论数据")
            with st.form("theory_auth_form"):
                pwd = st.text_input("密码", type="password")
                submit = st.form_submit_button("验证")
                if submit:
                    if pwd == THEORY_PASSWORD:
                        st.session_state.theory_authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            with st.form(key='theory_form', clear_on_submit=True):
                st.subheader("1. 基础信息")
                col1, col2, col3 = st.columns(3)
                with col1:
                    input_model_t = st.text_input("机型", value="宝莱坞", key="t_model")
                with col2:
                    input_stage_t = st.selectbox("阶段", STAGE_OPTIONS, index=0, key="t_stage")
                with col3:
                    input_mode_t = st.selectbox("模式", MODE_OPTIONS, index=0, key="t_mode")
                st.info("📌 理论数据的数据来源固定为：理论评估")

                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values_t = {}
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
                        input_values_t[field] = st.number_input(field, value=default_val, format="%.5f", step=0.00001, key=f"t_{field}")

                submitted_t = st.form_submit_button("保存理论数据")
                if submitted_t:
                    new_data = {
                        "机型": input_model_t,
                        "阶段": input_stage_t,
                        "模式": input_mode_t,
                        "数据来源": "理论评估",
                        "实测/理论": "理论",
                    }
                    new_data.update(input_values_t)
                    for field in ACTUAL_EXTRA_FIELDS:
                        new_data[field] = ""
                    df = load_theory_data()
                    if df.empty:
                        df = pd.DataFrame([new_data])
                    else:
                        for k in new_data.keys():
                            if k not in df.columns:
                                df[k] = ""
                        df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                    save_theory_data(df)
                    st.success("✅ 理论数据保存成功！")
                    st.rerun()

            st.markdown("---")
            st.subheader("📜 理论历史数据管理")
            df_theory = load_theory_data()
            if not df_theory.empty:
                display_df_t = df_theory.copy()
                for col in COMMON_FIELDS:
                    if col in display_df_t.columns:
                        display_df_t[col] = display_df_t[col].apply(lambda x: f'{x:.5f}' if pd.notna(x) and x != '' else x)
                edited_df_t = st.data_editor(display_df_t, num_rows="dynamic", key="editor_theory", use_container_width=True)
                if st.button("💾 保存理论表格修改", key="save_theory_edit"):
                    for col in COMMON_FIELDS:
                        if col in edited_df_t.columns:
                            edited_df_t[col] = pd.to_numeric(edited_df_t[col], errors='coerce')
                    edited_df_t['数据来源'] = '理论评估'
                    save_theory_data(edited_df_t)
                    st.success("理论历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无理论历史数据")

    # ---------- 数据分析（公开）----------
    with tab3:
        st.header("数据查询与分析")

        with st.expander("筛选条件", expanded=True):
            if st.button("+ 添加筛选组"):
                new_id = len(st.session_state.filter_groups)
                st.session_state.filter_groups.append({'id': new_id})
                st.rerun()

            all_filters = []
            for i, group in enumerate(st.session_state.filter_groups):
                st.markdown(f"**筛选组 {i + 1}**")
                cols = st.columns([2, 1, 1, 2, 1])
                with cols[0]:
                    f_model = st.text_input("机型", key=f"model_{i}")
                with cols[1]:
                    f_stage = st.selectbox("阶段", ["全部"] + STAGE_OPTIONS, key=f"stage_{i}")
                with cols[2]:
                    f_mode = st.selectbox("模式", ["全部"] + MODE_OPTIONS, key=f"mode_{i}")
                with cols[3]:
                    f_source = st.selectbox("数据来源", ["全部"] + SOURCE_OPTIONS, key=f"source_{i}")
                with cols[4]:
                    st.write("")
                    st.write("")
                    if st.button("删除", key=f"del_{i}"):
                        st.session_state.filter_groups.pop(i)
                        st.rerun()
                all_filters.append({
                    "model": f_model,
                    "stage": f_stage,
                    "mode": f_mode,
                    "source": f_source
                })
            st.divider()

        if st.button("执行查询", type="primary"):
            df_all = get_data_with_source()
            if df_all.empty:
                st.warning("暂无任何数据")
            else:
                final_df = pd.DataFrame()
                for f in all_filters:
                    mask = pd.Series([True] * len(df_all))
                    if f['model']:
                        mask &= df_all['机型'].str.contains(f['model'], case=False, na=False)
                    if f['stage'] != "全部":
                        mask &= df_all['阶段'] == f['stage']
                    if f['mode'] != "全部":
                        mask &= df_all['模式'] == f['mode']
                    if f['source'] != "全部":
                        mask &= df_all['数据来源'] == f['source']
                    filtered_subset = df_all[mask]
                    final_df = pd.concat([final_df, filtered_subset])
                final_df.drop_duplicates(inplace=True)
                if final_df.empty:
                    st.info("未找到符合条件的数据")
                else:
                    st.success(f"查询结果 (共 {len(final_df)} 条)")
                    display_final_df = final_df.copy()
                    for col in COMMON_FIELDS:
                        if col in display_final_df.columns:
                            display_final_df[col] = display_final_df[col].apply(
                                lambda x: f'{float(x):.5f}' if pd.notna(x) and x != '' and x != 0 else x
                            )
                    st.dataframe(display_final_df, use_container_width=True)

    # ---------- 光机信息（公开）----------
    with tab4:
        st.header("光机信息查询")
        st.markdown("此表格用于记录各机型的光机相关信息，支持添加、编辑、删除操作。")
        df_optics = load_optics_data()
        edited_optics = st.data_editor(
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
        if st.button("💾 保存光机信息", key="save_optics"):
            edited_optics_clean = edited_optics.dropna(how='all').reset_index(drop=True)
            save_optics_data(edited_optics_clean)
            st.success("光机信息已保存！")
            st.rerun()
        st.caption("提示：在表格最后一行下方点击“+”可添加新行，勾选行前面的复选框后点击上方出现的“删除”按钮可删除行。")


if __name__ == "__main__":
    main()
