import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import numpy as np

# ================== Google Sheets 配置 ==================
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SPREADSHEET_ID = '1JW1fQRYMts20yc4ctV8aZYzyhbb6wmLhEhMSH1EtIUU'
WORKSHEET_ACTUAL = '实测数据'
WORKSHEET_THEORY = '理论数据'
WORKSHEET_OPTICS = '光机信息'
WORKSHEET_MODES = '模式配置'
WORKSHEET_THERMAL = '散热数据'

# ================== 全局常量 ==================
STAGE_OPTIONS = ["EVT", "DVT", "PVT", "MP"]
DEFAULT_MODE_OPTIONS = [
    "三段AI", "三段运动", "三段filmmaker", "三段电影",
    "五段AI", "五段filmmaker", "五段电影",
    "性能", "overlap"
]
SOURCE_OPTIONS = ["研发测试", "产线测试", "认证机构", "理论评估"]
EVALUATION_OBJECTS = ["光机", "整机"]
COMMON_FIELDS = ["亮度", "色点x", "色点y", "色温", "Duv", "SSI", "灯温", "duty", "对比度", "色域"]
ACTUAL_EXTRA_FIELDS = ["照度计编号", "整机SN", "版本-固件", "版本-image", "环境温度"]
THEORY_EXTRA_FIELDS = ["评估对象", "照度计型号", "备注"]

THERMAL_FIELDS = [
    "机型", "阶段", "模式", "光机功耗", "整机功耗", "环境温度", "风扇转速",
    "灯温", "DMD光功率", "DMD overfill占比", "DMD吸收系数", "DMD光-热功耗",
    "DMD电功耗", "DMD总功耗", "DMD spec", "DMD-TP1", "DMD余量"
]
THERMAL_AVG_FIELDS = [f for f in THERMAL_FIELDS if f not in ["机型", "阶段", "模式"]]

DEFAULT_OPTICS_FIELDS = []
ACTUAL_PASSWORD = "Aa123456"
THEORY_PASSWORD = "Aa654321"
THERMAL_PASSWORD = "Aa888888"

UNWANTED_THEORY_COLS = ["照度计编号", "整机SN", "版本-固件", "版本-image"]
AVG_FIELDS = ["亮度", "色点x", "色点y", "色温", "Duv", "SSI", "对比度", "色域"]

# ================== JSON 安全转换 ==================
def make_json_safe(value):
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (np.generic, np.ndarray)):
        try:
            return value.item()
        except:
            return str(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)

# ================== Google Sheets 客户端 ==================
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
            if headers:
                ws.update([headers])
        return ws
    except gspread.exceptions.WorksheetNotFound:
        cols = len(headers) if headers else 1
        ws = sh.add_worksheet(title=sheet_title, rows=1, cols=cols)
        if headers:
            ws.update([headers])
        else:
            ws.update([[""]])
        return ws

# ================== 数据读写（带重试） ==================
def load_data_from_sheet(worksheet_name, remove_unwanted_cols=False, add_missing_cols=True, default_headers=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            ws = get_worksheet(worksheet_name)
            all_values = ws.get_all_values()
            if not all_values:
                if default_headers:
                    ws.update([default_headers])
                    return pd.DataFrame(columns=default_headers)
                return pd.DataFrame()
            headers = [h.strip() for h in all_values[0]]
            data_rows = all_values[1:] if len(all_values) > 1 else []
            df = pd.DataFrame(data_rows, columns=headers)
            df = df.replace(['', 'nan', 'None'], None)

            if worksheet_name == WORKSHEET_THERMAL:
                numeric_fields = ["光机功耗", "整机功耗", "环境温度", "风扇转速", "灯温",
                                  "DMD光功率", "DMD overfill占比", "DMD吸收系数", "DMD光-热功耗",
                                  "DMD电功耗", "DMD总功耗", "DMD余量"]
                for col in numeric_fields:
                    if col in df.columns:
                        df[col] = df[col].apply(lambda x: safe_float_convert(x) if x not in [None, ""] else None)
            else:
                for col in COMMON_FIELDS:
                    if col in df.columns:
                        df[col] = df[col].apply(lambda x: safe_float_convert(x) if x not in [None, ""] else None)

            if remove_unwanted_cols and worksheet_name == WORKSHEET_THEORY:
                cols_to_drop = [c for c in UNWANTED_THEORY_COLS if c in df.columns]
                if cols_to_drop:
                    df = df.drop(columns=cols_to_drop)
                    save_data_to_sheet(df, worksheet_name)

            if add_missing_cols and worksheet_name == WORKSHEET_THEORY:
                for col in ["评估对象", "照度计型号", "备注"]:
                    if col not in df.columns:
                        df[col] = None

            if add_missing_cols and worksheet_name == WORKSHEET_ACTUAL:
                if "环境温度" not in df.columns:
                    df["环境温度"] = None

            if worksheet_name == WORKSHEET_OPTICS and default_headers is not None:
                if default_headers:
                    for col in default_headers:
                        if col not in df.columns:
                            df[col] = None
                    existing_custom = [c for c in df.columns if c not in default_headers]
                    df = df[default_headers + existing_custom]

            return df
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                st.warning(f"API 读限流，等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            st.error(f"读取工作表 {worksheet_name} 失败: {e}")
            return pd.DataFrame()

def save_data_to_sheet(df, worksheet_name, max_retries=3):
    if worksheet_name == WORKSHEET_THEORY:
        cols_to_drop = [c for c in UNWANTED_THEORY_COLS if c in df.columns]
        if cols_to_drop:
            df = df.drop(columns=cols_to_drop)
        for col in ["评估对象", "照度计型号", "备注"]:
            if col not in df.columns:
                df[col] = None
    if worksheet_name == WORKSHEET_ACTUAL:
        if "环境温度" not in df.columns:
            df["环境温度"] = None

    for attempt in range(max_retries):
        try:
            ws = get_worksheet(worksheet_name)
            ws.clear()
            if not df.empty:
                df_clean = df.where(pd.notnull(df), None)
                rows = [df_clean.columns.tolist()] + df_clean.values.tolist()
                clean_rows = []
                for row in rows:
                    clean_rows.append([make_json_safe(cell) for cell in row])
                ws.update(clean_rows)
            else:
                if df.columns.tolist():
                    ws.update([df.columns.tolist()])
                else:
                    ws.update([[""]])
            return
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                st.warning(f"API 写限流，等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            st.error(f"保存失败: {e}")
            raise

# ================== 模式配置 ==================
@st.cache_data(ttl=300)
def load_mode_options():
    for attempt in range(3):
        try:
            ws = get_worksheet(WORKSHEET_MODES)
            records = ws.get_all_records()
            if records:
                modes = [r['模式'] for r in records if r.get('模式')]
                return modes if modes else DEFAULT_MODE_OPTIONS.copy()
            else:
                ws.update([['模式']] + [[m] for m in DEFAULT_MODE_OPTIONS])
                return DEFAULT_MODE_OPTIONS.copy()
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
            else:
                raise
        except gspread.exceptions.WorksheetNotFound:
            sh = get_spreadsheet()
            ws = sh.add_worksheet(title=WORKSHEET_MODES, rows=1, cols=1)
            ws.update([['模式']] + [[m] for m in DEFAULT_MODE_OPTIONS])
            return DEFAULT_MODE_OPTIONS.copy()

def add_new_mode(mode_name):
    if not mode_name or not mode_name.strip():
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
    theory_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + THEORY_EXTRA_FIELDS
    thermal_headers = THERMAL_FIELDS.copy()
    ensure_worksheet_exists(WORKSHEET_ACTUAL, actual_headers)
    ensure_worksheet_exists(WORKSHEET_THEORY, theory_headers)
    ensure_worksheet_exists(WORKSHEET_THERMAL, thermal_headers)
    ensure_worksheet_exists(WORKSHEET_OPTICS, [])
    load_mode_options()
    df_theory = load_theory_data()
    if "评估对象" not in df_theory.columns or "照度计型号" not in df_theory.columns or "备注" not in df_theory.columns:
        save_theory_data(df_theory)
    df_actual = load_actual_data()
    if "环境温度" not in df_actual.columns:
        df_actual["环境温度"] = None
        save_actual_data(df_actual)

@st.cache_data(ttl=300)
def load_actual_data():
    return load_data_from_sheet(WORKSHEET_ACTUAL, add_missing_cols=True)

def save_actual_data(df):
    save_data_to_sheet(df, WORKSHEET_ACTUAL)

@st.cache_data(ttl=300)
def load_theory_data():
    return load_data_from_sheet(WORKSHEET_THEORY, remove_unwanted_cols=True, add_missing_cols=True)

def save_theory_data(df):
    save_data_to_sheet(df, WORKSHEET_THEORY)

@st.cache_data(ttl=300)
def load_optics_data():
    return load_data_from_sheet(WORKSHEET_OPTICS, default_headers=[])

def save_optics_data(df):
    save_data_to_sheet(df, WORKSHEET_OPTICS)

@st.cache_data(ttl=300)
def load_thermal_data():
    return load_data_from_sheet(WORKSHEET_THERMAL, default_headers=THERMAL_FIELDS)

def save_thermal_data(df):
    save_data_to_sheet(df, WORKSHEET_THERMAL)

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

def process_uploaded_file(uploaded_file, expected_headers, is_actual=True):
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file, dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)
        df.columns = df.columns.str.strip()
        required_cols = ['机型', '阶段', '模式']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"文件缺少必要列: {missing}")
            return None, False
        for col in expected_headers:
            if col not in df.columns:
                df[col] = ""
        df = df[expected_headers]
        df = df.replace(['nan', 'None', ''], None)
        for col in COMMON_FIELDS:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: safe_float_convert(x) if x not in [None, ""] else None)
        if is_actual:
            df['实测/理论'] = '实测'
        else:
            df['实测/理论'] = '理论'
            df['数据来源'] = '理论评估'
        return df, True
    except Exception as e:
        st.error(f"文件解析失败: {e}")
        return None, False

def process_thermal_uploaded_file(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file, dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)
        df.columns = df.columns.str.strip()
        required_cols = ['机型', '阶段', '模式']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"文件缺少必要列: {missing}")
            return None, False
        for col in THERMAL_FIELDS:
            if col not in df.columns:
                df[col] = None
        df = df[THERMAL_FIELDS]
        df = df.replace(['nan', 'None', ''], None)
        numeric_fields = ["光机功耗", "整机功耗", "环境温度", "风扇转速", "灯温",
                          "DMD光功率", "DMD overfill占比", "DMD吸收系数", "DMD光-热功耗",
                          "DMD电功耗", "DMD总功耗", "DMD余量"]
        for col in numeric_fields:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: safe_float_convert(x) if x not in [None, ""] else None)
        return df, True
    except Exception as e:
        st.error(f"文件解析失败: {e}")
        return None, False

# ================== 获取机型选项（带缓存） ==================
@st.cache_data(ttl=300)
def get_available_models_for_luminance():
    """获取亮度数据（实测+理论）中的所有机型"""
    df_actual = load_actual_data()
    df_theory = load_theory_data()
    models = set()
    if not df_actual.empty and '机型' in df_actual.columns:
        models.update(df_actual['机型'].dropna().unique())
    if not df_theory.empty and '机型' in df_theory.columns:
        models.update(df_theory['机型'].dropna().unique())
    return sorted(["全部"] + list(models))

@st.cache_data(ttl=300)
def get_available_models_for_thermal():
    """获取散热数据中的所有机型"""
    df_thermal = load_thermal_data()
    if df_thermal.empty or '机型' not in df_thermal.columns:
        return ["全部"]
    models = df_thermal['机型'].dropna().unique()
    return sorted(["全部"] + list(models))

# ================== 独立表格的移动/平均值函数 ==================
def move_selected_row_up_table(df, group_key):
    if '_selected' not in df.columns:
        df['_selected'] = False
    df = df.reset_index(drop=True)
    selected = df['_selected'] == True
    selected_idx = selected[selected].index.tolist()
    if not selected_idx:
        st.warning(f"组 {group_key+1}：请先勾选要移动的行")
        return df
    idx = selected_idx[0]
    if idx == 0:
        st.warning(f"组 {group_key+1}：已经是第一行，无法上移")
        return df
    order = list(range(len(df)))
    order[idx], order[idx-1] = order[idx-1], order[idx]
    moved_df = df.iloc[order].reset_index(drop=True)
    moved_df['_selected'] = False
    moved_df.loc[idx-1, '_selected'] = True
    return moved_df

def move_selected_row_down_table(df, group_key):
    if '_selected' not in df.columns:
        df['_selected'] = False
    df = df.reset_index(drop=True)
    selected = df['_selected'] == True
    selected_idx = selected[selected].index.tolist()
    if not selected_idx:
        st.warning(f"组 {group_key+1}：请先勾选要移动的行")
        return df
    idx = selected_idx[0]
    if idx == len(df) - 1:
        st.warning(f"组 {group_key+1}：已经是最后一行，无法下移")
        return df
    order = list(range(len(df)))
    order[idx], order[idx+1] = order[idx+1], order[idx]
    moved_df = df.iloc[order].reset_index(drop=True)
    moved_df['_selected'] = False
    moved_df.loc[idx+1, '_selected'] = True
    return moved_df

def compute_average_for_table(df, avg_fields, group_key, query_type):
    if '_selected' not in df.columns:
        st.warning(f"组 {group_key+1}：没有可选中的行")
        return None
    selected_df = df[df['_selected'] == True]
    if selected_df.empty:
        st.warning(f"组 {group_key+1}：请先勾选要计算平均值的行")
        return None
    available_fields = [col for col in avg_fields if col in selected_df.columns]
    if not available_fields:
        st.warning(f"组 {group_key+1}：没有可计算平均值的数字字段")
        return None
    for col in available_fields:
        selected_df[col] = pd.to_numeric(selected_df[col], errors='coerce')
    means = selected_df[available_fields].mean()
    desc = f"{datetime.now().strftime('%H:%M:%S')} | {query_type} | 选中 {len(selected_df)} 行"
    return desc, means

# ================== Session 初始化 ==================
def init_session_state():
    if 'filter_groups' not in st.session_state:
        st.session_state.filter_groups = [{'id': 0, 'query_type': "亮度数据", 'filters': {"model": "全部", "stage": "全部", "mode": "全部", "source": "全部"}}]
    for i, g in enumerate(st.session_state.filter_groups):
        if 'query_type' not in g:
            g['query_type'] = "亮度数据"
        if 'filters' not in g:
            g['filters'] = {"model": "全部", "stage": "全部", "mode": "全部", "source": "全部"}
        # 确保 model 字段存在且不为空字符串（兼容旧数据）
        if 'model' not in g['filters'] or g['filters']['model'] == "":
            g['filters']['model'] = "全部"
    if 'actual_authenticated' not in st.session_state:
        st.session_state.actual_authenticated = False
    if 'theory_authenticated' not in st.session_state:
        st.session_state.theory_authenticated = False
    if 'thermal_authenticated' not in st.session_state:
        st.session_state.thermal_authenticated = False
    if 'selected_mode_actual' not in st.session_state:
        st.session_state.selected_mode_actual = DEFAULT_MODE_OPTIONS[0]
    if 'selected_mode_theory' not in st.session_state:
        st.session_state.selected_mode_theory = DEFAULT_MODE_OPTIONS[0]
    if 'selected_mode_thermal' not in st.session_state:
        st.session_state.selected_mode_thermal = DEFAULT_MODE_OPTIONS[0]
    if 'show_add_mode_actual' not in st.session_state:
        st.session_state.show_add_mode_actual = False
    if 'show_add_mode_theory' not in st.session_state:
        st.session_state.show_add_mode_theory = False
    if 'show_add_mode_thermal' not in st.session_state:
        st.session_state.show_add_mode_thermal = False
    if 'group_results' not in st.session_state:
        st.session_state.group_results = {}
    if 'group_avg_history' not in st.session_state:
        st.session_state.group_avg_history = {}

# ================== 主程序 UI ==================
def main():
    st.set_page_config(layout="wide", page_title="光学数据管理系统")
    st.title("📊 光学数据管理系统")
    init_session_state()

    if 'sheets_initialized' not in st.session_state:
        with st.spinner("正在检查/初始化工作表..."):
            init_sheets()
            st.session_state.sheets_initialized = True

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "【查询】数据分析",
        "【录入】实测数据",
        "【录入】理论数据",
        "【录入】散热数据",
        "【查询】光机信息"
    ])

    # -------------------- 数据分析查询（多组独立，机型改为下拉选择） --------------------
    with tab1:
        st.header("数据查询与分析")
        with st.expander("筛选组管理", expanded=True):
            if st.button("+ 添加筛选组"):
                new_id = len(st.session_state.filter_groups)
                st.session_state.filter_groups.append({
                    'id': new_id,
                    'query_type': "亮度数据",
                    'filters': {"model": "全部", "stage": "全部", "mode": "全部", "source": "全部"}
                })
                st.rerun()
            
            for i, group in enumerate(st.session_state.filter_groups):
                st.markdown(f"---\n#### 筛选组 {i+1}")
                cols = st.columns([2, 2, 2, 2, 1])
                with cols[0]:
                    new_query_type = st.selectbox(
                        "查询类型",
                        ["亮度数据", "散热数据"],
                        index=0 if group['query_type'] == "亮度数据" else 1,
                        key=f"group_query_type_{i}"
                    )
                    if new_query_type != group['query_type']:
                        group['query_type'] = new_query_type
                        # 切换类型时重置机型选项为"全部"
                        group['filters']['model'] = "全部"
                        st.rerun()
                with cols[1]:
                    # 根据当前查询类型获取机型选项
                    if group['query_type'] == "亮度数据":
                        model_options = get_available_models_for_luminance()
                    else:
                        model_options = get_available_models_for_thermal()
                    # 确保当前选中的值在选项中，否则设为"全部"
                    current_model = group['filters'].get('model', '全部')
                    if current_model not in model_options:
                        current_model = "全部"
                        group['filters']['model'] = "全部"
                    selected_model = st.selectbox(
                        "机型",
                        options=model_options,
                        index=model_options.index(current_model),
                        key=f"group_model_{i}"
                    )
                    group['filters']['model'] = selected_model
                with cols[2]:
                    stage = st.selectbox("阶段", ["全部"] + STAGE_OPTIONS, index=0 if group['filters']['stage'] == "全部" else STAGE_OPTIONS.index(group['filters']['stage'])+1, key=f"group_stage_{i}")
                    group['filters']['stage'] = stage
                with cols[3]:
                    mode_options = load_mode_options()
                    mode_idx = 0
                    if group['filters']['mode'] != "全部" and group['filters']['mode'] in mode_options:
                        mode_idx = mode_options.index(group['filters']['mode']) + 1
                    mode = st.selectbox("模式", ["全部"] + mode_options, index=mode_idx, key=f"group_mode_{i}")
                    group['filters']['mode'] = mode
                with cols[4]:
                    if st.button("删除", key=f"del_group_{i}"):
                        st.session_state.filter_groups.pop(i)
                        # 清理存储
                        keys_to_del = [k for k in st.session_state.group_results.keys() if k.endswith(f"_{i}") or k == f"result_{i}"]
                        for k in keys_to_del:
                            del st.session_state.group_results[k]
                        if f"avg_history_{i}" in st.session_state.group_avg_history:
                            del st.session_state.group_avg_history[f"avg_history_{i}"]
                        st.rerun()
                
                if group['query_type'] == "亮度数据":
                    # ================== 修复点：安全处理数据来源下拉框的索引 ==================
                    source_options = ["全部"] + SOURCE_OPTIONS
                    current_source = group['filters'].get('source', '全部')
                    # 如果当前值不在 source_options 中，默认选“全部”
                    try:
                        source_idx = source_options.index(current_source)
                    except ValueError:
                        source_idx = 0
                        # 修复存储的非法值（可选，避免下次再出错）
                        group['filters']['source'] = "全部"
                    source = st.selectbox(
                        "数据来源",
                        source_options,
                        index=source_idx,
                        key=f"group_source_{i}"
                    )
                    group['filters']['source'] = source
                else:
                    group['filters']['source'] = None
            
            if st.button("执行所有查询", type="primary"):
                for i, group in enumerate(st.session_state.filter_groups):
                    query_type = group['query_type']
                    filters = group['filters']
                    if query_type == "亮度数据":
                        df_all = get_data_with_source()
                        if df_all.empty:
                            st.session_state.group_results[f"result_{i}"] = pd.DataFrame()
                        else:
                            mask = pd.Series([True] * len(df_all))
                            if filters['model'] != "全部":
                                mask &= df_all['机型'].str.contains(filters['model'], case=False, na=False)
                            if filters['stage'] != "全部":
                                mask &= df_all['阶段'] == filters['stage']
                            if filters['mode'] != "全部":
                                mask &= df_all['模式'] == filters['mode']
                            if filters.get('source') and filters['source'] != "全部":
                                mask &= df_all['数据来源'] == filters['source']
                            final = df_all[mask].copy()
                            if final.empty:
                                st.session_state.group_results[f"result_{i}"] = pd.DataFrame()
                            else:
                                final['_selected'] = False
                                st.session_state.group_results[f"result_{i}"] = final
                    else:
                        df_thermal = load_thermal_data()
                        if df_thermal.empty:
                            st.session_state.group_results[f"result_{i}"] = pd.DataFrame()
                        else:
                            mask = pd.Series([True] * len(df_thermal))
                            if filters['model'] != "全部":
                                mask &= df_thermal['机型'].str.contains(filters['model'], case=False, na=False)
                            if filters['stage'] != "全部":
                                mask &= df_thermal['阶段'] == filters['stage']
                            if filters['mode'] != "全部":
                                mask &= df_thermal['模式'] == filters['mode']
                            final = df_thermal[mask].copy()
                            if final.empty:
                                st.session_state.group_results[f"result_{i}"] = pd.DataFrame()
                            else:
                                final['_selected'] = False
                                st.session_state.group_results[f"result_{i}"] = final
                st.rerun()
        
        # 显示每个组的查询结果
        for i, group in enumerate(st.session_state.filter_groups):
            result_key = f"result_{i}"
            if result_key in st.session_state.group_results:
                df = st.session_state.group_results[result_key]
                if df is not None and not df.empty:
                    st.markdown(f"#### 筛选组 {i+1} 查询结果")
                    query_type = group['query_type']
                    display_cols = [c for c in df.columns if c != '_selected']
                    display_df = df[display_cols].copy()
                    format_fields = COMMON_FIELDS if query_type == "亮度数据" else THERMAL_AVG_FIELDS
                    display_df = format_dataframe_for_display(display_df, format_fields)
                    display_df.insert(0, '_selected', df['_selected'])
                    
                    edited_df = st.data_editor(
                        display_df,
                        key=f"query_result_editor_{i}",
                        width='stretch',
                        column_config={"_selected": st.column_config.CheckboxColumn("选择", default=False)},
                        hide_index=False,
                    )
                    if edited_df is not None and '_selected' in edited_df.columns:
                        df['_selected'] = edited_df['_selected']
                        st.session_state.group_results[result_key] = df
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button(f"⬆️ 上移选中行", key=f"up_{i}"):
                            current = st.session_state.group_results[result_key]
                            if current is not None and not current.empty:
                                moved = move_selected_row_up_table(current, i)
                                st.session_state.group_results[result_key] = moved
                                st.rerun()
                    with col2:
                        if st.button(f"⬇️ 下移选中行", key=f"down_{i}"):
                            current = st.session_state.group_results[result_key]
                            if current is not None and not current.empty:
                                moved = move_selected_row_down_table(current, i)
                                st.session_state.group_results[result_key] = moved
                                st.rerun()
                    with col3:
                        if st.button(f"📊 计算平均值", key=f"avg_{i}"):
                            current = st.session_state.group_results[result_key]
                            if current is not None and not current.empty:
                                avg_fields = AVG_FIELDS if query_type == "亮度数据" else THERMAL_AVG_FIELDS
                                result = compute_average_for_table(current, avg_fields, i, query_type)
                                if result:
                                    desc, means = result
                                    mean_row = means.to_frame().T
                                    mean_row.insert(0, '计算时间/类型', desc)
                                    if f"avg_history_{i}" not in st.session_state.group_avg_history:
                                        st.session_state.group_avg_history[f"avg_history_{i}"] = []
                                    st.session_state.group_avg_history[f"avg_history_{i}"].append(mean_row)
                                    st.success(f"组 {i+1}：已记录平均值：{desc}")
                                    st.rerun()
                    
                    if f"avg_history_{i}" in st.session_state.group_avg_history and st.session_state.group_avg_history[f"avg_history_{i}"]:
                        st.markdown(f"**组 {i+1} 平均值对比记录**")
                        history_df = pd.concat(st.session_state.group_avg_history[f"avg_history_{i}"], ignore_index=True)
                        for col in history_df.columns:
                            if col != '计算时间/类型' and pd.api.types.is_numeric_dtype(history_df[col]):
                                history_df[col] = history_df[col].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "")
                        st.dataframe(history_df, width='stretch')
                        if st.button(f"🗑️ 清除组 {i+1} 平均值记录", key=f"clear_avg_{i}"):
                            st.session_state.group_avg_history[f"avg_history_{i}"] = []
                            st.rerun()
                    st.markdown("---")
                elif df is not None and df.empty:
                    st.info(f"筛选组 {i+1} 查询结果为空，请调整筛选条件后重新执行查询。")
                else:
                    st.info(f"筛选组 {i+1} 尚未执行查询，请设置筛选条件后点击「执行所有查询」。")
            else:
                st.info(f"筛选组 {i+1} 尚未执行查询，请设置筛选条件后点击「执行所有查询」。")

    # -------------------- 实测数据录入 --------------------
    with tab2:
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
            col_mode, col_add = st.columns([3, 1])
            with col_mode:
                mode_options = load_mode_options()
                selected_mode = st.selectbox("模式", mode_options, key="actual_mode_select",
                                             index=mode_options.index(st.session_state.selected_mode_actual) if st.session_state.selected_mode_actual in mode_options else 0)
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

            st.subheader("📁 批量导入实测数据")
            uploaded_file_actual = st.file_uploader("上传 CSV 或 Excel 文件（表头需与实测数据格式一致）",
                                                    type=['csv', 'xlsx', 'xls'], key="actual_uploader")
            if uploaded_file_actual is not None:
                expected_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + ACTUAL_EXTRA_FIELDS
                df_upload, success = process_uploaded_file(uploaded_file_actual, expected_headers, is_actual=True)
                if success:
                    st.success(f"成功读取 {len(df_upload)} 条记录")
                    st.dataframe(df_upload.head(10), width='stretch')
                    if st.button("确认追加到实测数据", key="confirm_actual_upload"):
                        df_existing = load_actual_data()
                        df_new = pd.concat([df_existing, df_upload], ignore_index=True) if not df_existing.empty else df_upload
                        save_actual_data(df_new)
                        st.success(f"已追加 {len(df_upload)} 条实测数据")
                        st.rerun()

            st.subheader("✍️ 手动录入单条数据")
            with st.form(key='actual_form', clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS)
                with col3:
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
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_actual", width='stretch')
                if st.button("💾 保存实测表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = edited[col].apply(lambda x: safe_float_convert(x) if isinstance(x, str) else x)
                    save_actual_data(edited)
                    st.success("实测历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无实测历史数据")

    # -------------------- 理论数据录入 --------------------
    with tab3:
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
            col_mode, col_add = st.columns([3, 1])
            with col_mode:
                mode_options = load_mode_options()
                selected_mode = st.selectbox("模式", mode_options, key="theory_mode_select",
                                             index=mode_options.index(st.session_state.selected_mode_theory) if st.session_state.selected_mode_theory in mode_options else 0)
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

            st.subheader("📁 批量导入理论数据")
            uploaded_file_theory = st.file_uploader("上传 CSV 或 Excel 文件（表头需与理论数据格式一致）",
                                                    type=['csv', 'xlsx', 'xls'], key="theory_uploader")
            if uploaded_file_theory is not None:
                expected_headers = ['机型', '阶段', '模式', '数据来源', '实测/理论'] + COMMON_FIELDS + THEORY_EXTRA_FIELDS
                df_upload, success = process_uploaded_file(uploaded_file_theory, expected_headers, is_actual=False)
                if success:
                    st.success(f"成功读取 {len(df_upload)} 条记录")
                    st.dataframe(df_upload.head(10), width='stretch')
                    if st.button("确认追加到理论数据", key="confirm_theory_upload"):
                        df_existing = load_theory_data()
                        df_new = pd.concat([df_existing, df_upload], ignore_index=True) if not df_existing.empty else df_upload
                        save_theory_data(df_new)
                        st.success(f"已追加 {len(df_upload)} 条理论数据")
                        st.rerun()

            st.subheader("✍️ 手动录入单条数据")
            with st.form(key='theory_form', clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞", key="t_model")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS, key="t_stage")
                with col3:
                    st.text_input("模式", value=st.session_state.selected_mode_theory, disabled=True)
                with col4:
                    input_eval_obj = st.selectbox("评估对象", EVALUATION_OBJECTS, key="t_eval")
                
                st.info("📌 理论数据的数据来源固定为：理论评估")
                st.subheader("2. 光学参数")
                cols = st.columns(len(COMMON_FIELDS))
                input_values = {}
                for i, field in enumerate(COMMON_FIELDS):
                    with cols[i]:
                        input_values[field] = st.text_input(field, value="", key=f"theory_{field}",
                                                            placeholder="留空或填入数字/文字")
                
                st.subheader("3. 附加信息")
                extra_cols = st.columns(len(THEORY_EXTRA_FIELDS))
                input_extras = {}
                with extra_cols[0]:
                    input_extras["照度计型号"] = st.text_input("照度计型号", key="t_luxmeter")
                with extra_cols[1]:
                    input_extras["备注"] = st.text_input("备注", key="t_remark")

                if st.form_submit_button("保存理论数据"):
                    converted = {f: safe_float_convert(input_values[f]) for f in COMMON_FIELDS}
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": st.session_state.selected_mode_theory,
                        "数据来源": "理论评估",
                        "实测/理论": "理论",
                        **converted,
                        "评估对象": input_eval_obj,
                        "照度计型号": input_extras["照度计型号"],
                        "备注": input_extras["备注"]
                    }
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
            col_refresh, _ = st.columns([1, 5])
            with col_refresh:
                if st.button("🔄 刷新理论数据", key="refresh_theory"):
                    st.cache_data.clear()
                    st.rerun()
            df_theory = load_theory_data()
            if not df_theory.empty:
                display_df = format_dataframe_for_display(df_theory, COMMON_FIELDS)
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_theory", width='stretch')
                if st.button("💾 保存理论表格修改"):
                    for col in COMMON_FIELDS:
                        if col in edited:
                            edited[col] = edited[col].apply(lambda x: safe_float_convert(x) if isinstance(x, str) else x)
                    for col in ["评估对象", "照度计型号", "备注"]:
                        if col not in edited.columns:
                            edited[col] = None
                    edited['数据来源'] = '理论评估'
                    save_theory_data(edited)
                    st.success("理论历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无理论历史数据")
                with st.expander("💡 数据不显示怎么办？"):
                    st.markdown("""
                    - 请检查 Google Sheets 中的「理论数据」工作表，确保表头包含：机型、阶段、模式、数据来源、实测/理论、亮度、色点x、...、评估对象、照度计型号、备注。
                    - 如果表头不匹配，可以删除该工作表（先备份数据），程序会自动重建。
                    - 点击上方的「刷新理论数据」按钮清除缓存。
                    """)

    # -------------------- 散热数据录入 --------------------
    with tab4:
        st.header("散热数据录入")
        if not st.session_state.thermal_authenticated:
            st.warning("请输入密码以查看和操作散热数据")
            with st.form("thermal_auth_form"):
                pwd = st.text_input("密码", type="password")
                if st.form_submit_button("验证"):
                    if pwd == THERMAL_PASSWORD:
                        st.session_state.thermal_authenticated = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            col_mode, col_add = st.columns([3, 1])
            with col_mode:
                mode_options = load_mode_options()
                selected_mode = st.selectbox("模式", mode_options, key="thermal_mode_select",
                                             index=mode_options.index(st.session_state.selected_mode_thermal) if st.session_state.selected_mode_thermal in mode_options else 0)
                st.session_state.selected_mode_thermal = selected_mode
            with col_add:
                if st.button("➕ 新增模式", key="thermal_add_mode_btn"):
                    st.session_state.show_add_mode_thermal = True
            if st.session_state.show_add_mode_thermal:
                with st.popover("新增模式", use_container_width=True):
                    new_mode = st.text_input("新模式名称", key="thermal_new_mode_input")
                    if st.button("确定添加", key="thermal_confirm_add"):
                        if new_mode and new_mode.strip():
                            if add_new_mode(new_mode.strip()):
                                st.success(f"模式「{new_mode.strip()}」已添加")
                                st.session_state.show_add_mode_thermal = False
                                st.rerun()
                            else:
                                st.error("模式已存在或添加失败")
                        else:
                            st.warning("请输入模式名称")
                    if st.button("取消", key="thermal_cancel_add"):
                        st.session_state.show_add_mode_thermal = False
                        st.rerun()

            st.subheader("📁 批量导入散热数据")
            uploaded_file_thermal = st.file_uploader("上传 CSV 或 Excel 文件（表头需与散热数据格式一致）",
                                                    type=['csv', 'xlsx', 'xls'], key="thermal_uploader")
            if uploaded_file_thermal is not None:
                df_upload, success = process_thermal_uploaded_file(uploaded_file_thermal)
                if success:
                    st.success(f"成功读取 {len(df_upload)} 条记录")
                    st.dataframe(df_upload.head(10), width='stretch')
                    if st.button("确认追加到散热数据", key="confirm_thermal_upload"):
                        df_existing = load_thermal_data()
                        if df_existing.empty:
                            df_new = df_upload
                        else:
                            for col in THERMAL_FIELDS:
                                if col not in df_existing.columns:
                                    df_existing[col] = None
                            df_new = pd.concat([df_existing, df_upload], ignore_index=True)
                        save_thermal_data(df_new)
                        st.success(f"已追加 {len(df_upload)} 条散热数据")
                        st.rerun()

            st.subheader("✍️ 手动录入单条散热数据")
            with st.form(key='thermal_form', clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    input_model = st.text_input("机型", value="宝莱坞", key="thermal_model")
                with col2:
                    input_stage = st.selectbox("阶段", STAGE_OPTIONS, key="thermal_stage")
                with col3:
                    st.text_input("模式", value=st.session_state.selected_mode_thermal, disabled=True)
                
                st.subheader("散热参数")
                thermal_param_fields = [
                    "光机功耗", "整机功耗", "环境温度", "风扇转速", "灯温",
                    "DMD光功率", "DMD overfill占比", "DMD吸收系数", "DMD光-热功耗",
                    "DMD电功耗", "DMD总功耗", "DMD spec", "DMD-TP1", "DMD余量"
                ]
                cols = st.columns(2)
                input_values = {}
                for i, field in enumerate(thermal_param_fields):
                    with cols[i % 2]:
                        input_values[field] = st.text_input(field, value="", key=f"thermal_{field}",
                                                            placeholder="留空或填入数字/文字")
                
                if st.form_submit_button("保存散热数据"):
                    converted = {f: safe_float_convert(input_values[f]) for f in thermal_param_fields}
                    new_row = {
                        "机型": input_model,
                        "阶段": input_stage,
                        "模式": st.session_state.selected_mode_thermal,
                        **converted
                    }
                    for col in THERMAL_FIELDS:
                        if col not in new_row:
                            new_row[col] = None
                    df = load_thermal_data()
                    if df.empty:
                        df = pd.DataFrame([new_row])
                    else:
                        for k in new_row:
                            if k not in df.columns:
                                df[k] = None
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    save_thermal_data(df)
                    st.success("✅ 散热数据保存成功！")
                    st.rerun()
            
            st.markdown("---")
            st.subheader("📜 散热历史数据管理")
            col_refresh, _ = st.columns([1, 5])
            with col_refresh:
                if st.button("🔄 刷新散热数据", key="refresh_thermal"):
                    st.cache_data.clear()
                    st.rerun()
            df_thermal = load_thermal_data()
            if not df_thermal.empty:
                numeric_fields = [f for f in THERMAL_FIELDS if f not in ["机型", "阶段", "模式"]]
                display_df = format_dataframe_for_display(df_thermal, numeric_fields)
                edited = st.data_editor(display_df, num_rows="dynamic", key="edit_thermal", width='stretch')
                if st.button("💾 保存散热表格修改"):
                    for col in numeric_fields:
                        if col in edited:
                            edited[col] = edited[col].apply(lambda x: safe_float_convert(x) if isinstance(x, str) else x)
                    save_thermal_data(edited)
                    st.success("散热历史数据已更新")
                    st.rerun()
            else:
                st.info("暂无散热历史数据")
                with st.expander("💡 首次使用说明"):
                    st.markdown("请通过上方的表单录入第一条散热数据，或通过批量导入功能添加数据。")

    # -------------------- 光机信息（无默认字段，用户自行添加） --------------------
    with tab5:
        st.header("光机信息查询与管理")
        st.markdown("此表格用于记录各机型的光机相关信息。**默认无任何字段**，请通过下方按钮添加自定义列。")
        st.markdown("点击「添加自定义字段」输入列名后，表格会增加对应列，您可以在表格中录入数据。")
        
        df_optics = load_optics_data()
        
        col_new, _ = st.columns([2, 3])
        with col_new:
            new_col_name = st.text_input("新字段名称（列名）", key="new_optics_col", placeholder="例如：机型、DMD型号、透镜型号等")
            if st.button("➕ 添加自定义字段", key="add_optics_col"):
                if new_col_name and new_col_name.strip():
                    new_col = new_col_name.strip()
                    if new_col not in df_optics.columns:
                        df_optics[new_col] = None
                        st.success(f"已添加字段: {new_col}")
                        save_optics_data(df_optics)
                        st.rerun()
                    else:
                        st.warning("该字段已存在")
                else:
                    st.warning("请输入字段名称")
        
        if not df_optics.empty:
            edited_df = st.data_editor(
                df_optics,
                num_rows="dynamic",
                width='stretch',
                key="optics_editor",
                column_config={col: st.column_config.TextColumn(col) for col in df_optics.columns}
            )
            if st.button("💾 保存光机信息", key="save_optics"):
                save_optics_data(edited_df)
                st.success("光机信息已保存！")
                st.rerun()
        else:
            st.info("当前没有任何字段，请使用上方输入框添加自定义字段。")
            if st.button("➕ 先添加第一个字段（如：机型）"):
                st.info("请在左侧输入框中输入字段名称后点击「添加自定义字段」")
        
        st.caption("提示：添加自定义字段后，表格会自动增加该列，您可以在表格中填写数据。支持动态增删行。")

if __name__ == "__main__":
    main()
