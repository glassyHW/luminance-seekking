#---V4.2修改查询界面需要依次输入录入界面密码才能使用bug，2025/05/08
import streamlit as st
import pandas as pd
import os

# --- 全局配置 ---
ACTUAL_DATA_FILE = 'actual_data.csv'
THEORY_DATA_FILE = 'theory_data.csv'
OPTICS_INFO_FILE = 'optics_info.csv'

# --- 核心枚举定义 ---
STAGE_OPTIONS = ["EVT", "DVT", "PVT", "MP"]
MODE_OPTIONS = [
    "三段AI", "三段运动", "三段filmmaker", "三段电影",
    "五段AI", "五段filmmaker", "五段电影",
    "性能", "overlap"
]
SOURCE_OPTIONS = ["研发测试", "产线测试", "认证机构", "理论评估"]

# --- 字段定义 ---
COMMON_FIELDS = ["亮度", "色点x", "色点y", "色温", "Duv", "SSI", "灯温", "duty", "对比度", "色域"]
ACTUAL_EXTRA_FIELDS = ["照度计编号", "整机SN", "版本-固件", "版本-image"]
OPTICS_FIELDS = ["机型", "DMD型号", "灯的型号（颗数）", "风扇型号", "DMD温度（包含余量）", "记录时间"]

# --- 默认密码 ---
ACTUAL_PASSWORD = "Aa123456"
THEORY_PASSWORD = "Aa654321"

# --- 工具函数 ---
def load_data(file_path):
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            for col in COMMON_FIELDS:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').round(5)
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def save_data(df, file_path):
    df_to_save = df.copy()
    for col in COMMON_FIELDS:
        if col in df_to_save.columns:
            df_to_save[col] = pd.to_numeric(df_to_save[col], errors='coerce').round(5)
    df_to_save.to_csv(file_path, index=False, float_format='%.5f')

def get_data_with_source():
    df_actual = load_data(ACTUAL_DATA_FILE)
    if not df_actual.empty:
        if '数据来源' not in df_actual.columns:
            df_actual['数据来源'] = '研发测试'
        df_actual['实测/理论'] = '实测'
        for col in COMMON_FIELDS:
            if col in df_actual.columns:
                df_actual[col] = pd.to_numeric(df_actual[col], errors='coerce').round(5)
    else:
        df_actual = pd.DataFrame(columns=['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + ACTUAL_EXTRA_FIELDS)

    df_theory = load_data(THEORY_DATA_FILE)
    if not df_theory.empty:
        df_theory['数据来源'] = '理论评估'
        df_theory['实测/理论'] = '理论'
        for col in COMMON_FIELDS:
            if col in df_theory.columns:
                df_theory[col] = pd.to_numeric(df_theory[col], errors='coerce').round(5)
    else:
        df_theory = pd.DataFrame(columns=['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS)

    df_all = pd.concat([df_actual, df_theory], ignore_index=True, sort=False)
    df_all = df_all.fillna("")
    return df_all

def load_optics_data():
    if os.path.exists(OPTICS_INFO_FILE):
        try:
            df = pd.read_csv(OPTICS_INFO_FILE)
            for col in OPTICS_FIELDS:
                if col not in df.columns:
                    df[col] = ""
            return df
        except Exception:
            return pd.DataFrame(columns=OPTICS_FIELDS)
    else:
        return pd.DataFrame(columns=OPTICS_FIELDS)

def save_optics_data(df):
    df_to_save = df[OPTICS_FIELDS].copy()
    df_to_save.to_csv(OPTICS_INFO_FILE, index=False)

# --- 初始化 Session State ---
def initialize_session_state():
    if 'filter_groups' not in st.session_state:
        st.session_state.filter_groups = [{'id': 0}]
    if 'actual_authenticated' not in st.session_state:
        st.session_state.actual_authenticated = False
    if 'theory_authenticated' not in st.session_state:
        st.session_state.theory_authenticated = False

initialize_session_state()

# --- 页面布局 ---
st.set_page_config(layout="wide", page_title="光学数据管理系统")
st.title("📊 光学数据管理系统")

tab1, tab2, tab3, tab4 = st.tabs(["【录入】实测数据", "【录入】理论数据", "【查询】数据分析", "【查询】光机信息"])

# ==========================================
# 实测数据录入（独立密码验证，不使用 st.stop()）
# ==========================================
with tab1:
    st.header("实测数据录入")

    if not st.session_state.actual_authenticated:
        st.warning("请输入密码以查看和操作实测数据")
        with st.form("actual_auth_form"):
            pwd = st.text_input("密码", type="password")
            submit_auth = st.form_submit_button("验证")
            if submit_auth:
                if pwd == ACTUAL_PASSWORD:
                    st.session_state.actual_authenticated = True
                    st.rerun()
                else:
                    st.error("密码错误")
        # 未认证时，不显示正文内容，但代码继续执行（不会 stop）
    else:
        # 已验证：显示完整内容（表单 + 历史管理）
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
                df = load_data(ACTUAL_DATA_FILE)
                if df.empty:
                    df = pd.DataFrame([new_data])
                else:
                    for k in new_data.keys():
                        if k not in df.columns:
                            df[k] = ""
                    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                save_data(df, ACTUAL_DATA_FILE)
                st.success("✅ 实测数据保存成功！")
                st.rerun()

        st.markdown("---")
        st.subheader("📜 实测历史数据管理")
        df_actual = load_data(ACTUAL_DATA_FILE)
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
                save_data(edited_df, ACTUAL_DATA_FILE)
                st.success("实测历史数据已更新")
                st.rerun()
        else:
            st.info("暂无实测历史数据")

# ==========================================
# 理论数据录入（独立密码验证）
# ==========================================
with tab2:
    st.header("理论数据录入")

    if not st.session_state.theory_authenticated:
        st.warning("请输入密码以查看和操作理论数据")
        with st.form("theory_auth_form"):
            pwd = st.text_input("密码", type="password")
            submit_auth = st.form_submit_button("验证")
            if submit_auth:
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
                df = load_data(THEORY_DATA_FILE)
                if df.empty:
                    df = pd.DataFrame([new_data])
                else:
                    for k in new_data.keys():
                        if k not in df.columns:
                            df[k] = ""
                    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                save_data(df, THEORY_DATA_FILE)
                st.success("✅ 理论数据保存成功！")
                st.rerun()

        st.markdown("---")
        st.subheader("📜 理论历史数据管理")
        df_theory = load_data(THEORY_DATA_FILE)
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
                save_data(edited_df_t, THEORY_DATA_FILE)
                st.success("理论历史数据已更新")
                st.rerun()
        else:
            st.info("暂无理论历史数据")

# ==========================================
# 数据查询与分析（完全公开，无任何密码检查）
# ==========================================
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

# ==========================================
# 光机信息查询与管理（完全公开）
# ==========================================
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