import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io


st.set_page_config(layout="wide")

# 1. Load Data from Google Sheets
@st.cache_data(ttl=86400, show_spinner=False) 
def load_data():
    # Read the Google credentials securely from Streamlit secrets
    credentials_dict = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credentials_dict)
    
    # Fetch the ID securely
    sheet_id = st.secrets["my_secure_sheet_id"]
    sh = gc.open_by_key(sheet_id) 
 
    # --- 1. LOAD RAW DATA ---
    ws_cluster = sh.worksheet("Cluster Profile")
    df_cluster = pd.DataFrame(ws_cluster.get_all_values()[1:], columns=ws_cluster.get_all_values()[0]) 
    
    ws_fca = sh.worksheet("FCA Profile") 
    df_fca = pd.DataFrame(ws_fca.get_all_values()[1:], columns=ws_fca.get_all_values()[0]) 
    
    ws_commodity = sh.worksheet("Commodity Profile") 
    df_commodity = pd.DataFrame(ws_commodity.get_all_values()[1:], columns=ws_commodity.get_all_values()[0]) 
    
    # NEW: Load CDP Profile Sheet
    ws_cdp = sh.worksheet("CDP CLUSTER PROFILE")
    df_cdp = pd.DataFrame(ws_cdp.get_all_values()[1:], columns=ws_cdp.get_all_values()[0])

    # --- 2. NORMALIZE COLUMNS ---
    for d in [df_cluster, df_fca, df_commodity, df_cdp]:
        d.columns = [str(c).strip() for c in d.columns]
        rename_map = {
            'Province': 'PROVINCE', 'Municipality': 'MUNICIPALITY', 'Barangay': 'BARANGAY',
            'Total members': 'Total Members', 'TOTAL MEMBERS': 'Total Members',
            'Male ': 'Male', 'Female ': 'Female'
        }
        d.rename(columns=rename_map, inplace=True)

    # Destroy trailing blank rows instantly
    if 'NAME OF CLUSTER' in df_cluster.columns: df_cluster = df_cluster[df_cluster['NAME OF CLUSTER'].astype(str).str.strip() != '']
    if 'NAME OF FCA MEMBERS' in df_fca.columns: df_fca = df_fca[df_fca['NAME OF FCA MEMBERS'].astype(str).str.strip() != '']
    if 'NAME OF FCA MEMBERS' in df_commodity.columns: df_commodity = df_commodity[df_commodity['NAME OF FCA MEMBERS'].astype(str).str.strip() != '']

    # Clean hidden spaces
    if 'NAME OF CLUSTER' in df_cluster.columns: df_cluster['NAME OF CLUSTER'] = df_cluster['NAME OF CLUSTER'].astype(str).str.strip()
    if 'NAME OF CLUSTER' in df_fca.columns: df_fca['NAME OF CLUSTER'] = df_fca['NAME OF CLUSTER'].astype(str).str.strip()
    if 'NAME OF FCA MEMBERS' in df_fca.columns: df_fca['NAME OF FCA MEMBERS'] = df_fca['NAME OF FCA MEMBERS'].astype(str).str.strip()
    if 'NAME OF FCA MEMBERS' in df_commodity.columns: df_commodity['NAME OF FCA MEMBERS'] = df_commodity['NAME OF FCA MEMBERS'].astype(str).str.strip()

    # Create a unique invisible ID for every FCA to guarantee perfect counting
    df_fca['_FCA_ID'] = range(len(df_fca))

    # ==========================================
    # --- 3. SMART MERGE (FCA PROFILE AS MASTER BASE) ---
    # ==========================================
    df = df_fca.copy()

    if 'NAME OF CLUSTER' in df.columns and 'NAME OF CLUSTER' in df_cluster.columns:
        cluster_cols_to_keep = ['NAME OF CLUSTER'] + [col for col in df_cluster.columns if col not in df.columns]
        df_cluster_clean = df_cluster[cluster_cols_to_keep].drop_duplicates(subset=['NAME OF CLUSTER']) 
        df = pd.merge(df, df_cluster_clean, on='NAME OF CLUSTER', how='left', suffixes=('', '_cluster'))
        
        for col in ['PROVINCE', 'MUNICIPALITY', 'BARANGAY']:
            if col in df.columns and f'{col}_cluster' in df.columns:
                df[col] = df[col].replace('', pd.NA).fillna(df[f'{col}_cluster'])
        df.drop(columns=[c for c in df.columns if c.endswith('_cluster')], inplace=True)

    if 'NAME OF FCA MEMBERS' in df.columns and 'NAME OF FCA MEMBERS' in df_commodity.columns:
        comm_cols_to_keep = ['NAME OF FCA MEMBERS'] + [col for col in df_commodity.columns if col not in df.columns]
        df_commodity_clean = df_commodity[comm_cols_to_keep]
        df = pd.merge(df, df_commodity_clean, on='NAME OF FCA MEMBERS', how='left', suffixes=('', '_comm'))
        df.drop(columns=[c for c in df.columns if c.endswith('_comm')], inplace=True)

    if 'PROVINCE' in df.columns: df['PROVINCE'] = df['PROVINCE'].astype(str).str.strip().str.title()
    if 'MUNICIPALITY' in df.columns: df['MUNICIPALITY'] = df['MUNICIPALITY'].astype(str).str.strip().str.title()
    
    # Ensure CDP Profile Province is also title-cased for perfect grouping
    if 'PROVINCE' in df_cdp.columns: df_cdp['PROVINCE'] = df_cdp['PROVINCE'].astype(str).str.strip().str.title()

    math_cols = ['Production Area\n (Has.)', 'Production Area\n (Trees, Heads)', 'Male', 'Female', 'Total Members']
    for col in math_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '', regex=False), errors='coerce').fillna(0)

    # Return BOTH datasets
    return df, df_cdp

with st.spinner("Fetching live data from Google Sheets..."):
    df, df_cdp = load_data()


# ==========================================
# --- STRICT VALIDATION HELPER ---
# Prevents blank/NaN rows from being counted
# ==========================================
def get_valid_mask(series):
    return ~series.astype(str).str.strip().str.lower().isin(['', 'nan', 'none', 'n/a', '<na>'])

# ==========================================
# --- REUSABLE TEXT-BOX FUNCTION FOR PROVINCIAL TAB ONLY ---
# ==========================================
def get_text_card(title, target_df, col_name, subset_col):
    if col_name not in target_df.columns or subset_col not in target_df.columns:
        return ""
    
    valid_mask = get_valid_mask(target_df[subset_col])
    clean_df = target_df[valid_mask].copy()
    
    clean_df = clean_df.drop_duplicates(subset=[subset_col])
    clean_df[col_name] = clean_df[col_name].fillna("")
    clean_df[col_name] = clean_df[col_name].astype(str).str.strip()
    
    clean_df.loc[clean_df[col_name].str.lower().isin(['', 'none', 'nan', 'na', 'n/a', '<na>']), col_name] = 'To Be Verified'
    clean_df[col_name] = clean_df[col_name].apply(lambda x: x if x == 'To Be Verified' else x.title())
    
    counts = clean_df[col_name].value_counts()
    
    lines_html = ""
    for label, count in counts.items():
        lines_html += f"<div style='margin-bottom: 20px; text-align: center;'><h2 style='margin:0; font-size: 26px; color: #222; line-height: 1;'>{count:,}</h2><p style='margin:0; font-size: 15px; color: #555; font-weight: bold;'>{label}</p></div>"
        
    return f"""
    <div style="border: 1px solid #ccc; border-radius: 5px; background-color: #ffffff; height: 380px; overflow-y: auto;">
        <div style="padding: 8px; text-align: center; border-bottom: 1px solid #ccc; background-color: #fafafa; margin-bottom: 15px; position: sticky; top: 0; z-index: 10;">
            <p style="margin: 0; font-size: 11px; color: #222; font-weight: bold; text-transform: uppercase;">{title}</p>
        </div>
        <div style="padding: 0 15px 15px 15px;">
            {lines_html}
        </div>
    </div>
    """


# 2. APP TITLE & REFRESH BUTTON
st.title("Department of Agriculture")
if st.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.divider()

# 3. SIDEBAR / BUTTONS COMPONENT (Affects Dashboard & Tables only)
st.sidebar.header("Main Dashboard Filters")

filtered_df = df.copy()

province = ["All"] + list(filtered_df['PROVINCE'].dropna().unique())
selected_province = st.sidebar.selectbox("Choose a Province:", province)
if selected_province != "All": filtered_df = filtered_df[filtered_df['PROVINCE'] == selected_province]

municipality = ["All"] + list(filtered_df['MUNICIPALITY'].dropna().unique())
selected_municipality = st.sidebar.selectbox("Choose a Municipality:", municipality)
if selected_municipality != "All": filtered_df = filtered_df[filtered_df['MUNICIPALITY'] == selected_municipality]

cluster = ["All"] + list(filtered_df['NAME OF CLUSTER'].dropna().unique())
selected_cluster = st.sidebar.selectbox("Choose a Cluster:", cluster)
if selected_cluster != "All": filtered_df = filtered_df[filtered_df['NAME OF CLUSTER'] == selected_cluster]

fca = ["All"] + list(filtered_df['NAME OF FCA MEMBERS'].dropna().unique())
selected_fca = st.sidebar.selectbox("Choose a FCA Member:", fca)
if selected_fca != "All": filtered_df = filtered_df[filtered_df['NAME OF FCA MEMBERS'] == selected_fca]

commodity_list = ["All"] + list(filtered_df['COMMODITY'].dropna().unique())
selected_commodity = st.sidebar.selectbox("Choose a Commodity:", commodity_list)
if selected_commodity != "All": filtered_df = filtered_df[filtered_df['COMMODITY'] == selected_commodity]

master_list = pd.concat([
    filtered_df['NAME OF CLUSTER'], filtered_df['PROVINCE'], filtered_df['MUNICIPALITY'],
    filtered_df['NAME OF BIG-BROTHER'], filtered_df['NAME OF FCA MEMBERS'],
    filtered_df['Status of Profiling'], filtered_df['COMMODITY']
]).dropna().unique()

available_options = [""] + sorted(list(master_list))
search_query = st.sidebar.selectbox("Search (Type or Select):", available_options)

if search_query != "All" and search_query != "":
    search_val = str(search_query).strip().lower()
    mask = filtered_df.astype(str).apply(lambda x: x.str.strip().str.lower() == search_val).any(axis=1)
    filtered_df = filtered_df[mask]


# 6. DASHBOARD SHOWCASE 
st.header("Reports")

# ==========================================
# --- CREATE THE TABS ---
# ==========================================
dash_tab, prov_tab, cdp_tab, table_tab = st.tabs(["Dashboard Overview", "Provincial Breakdown", "CDP Profile", "Data Tables"])

# --- HTML/CSS SHARED TEMPLATES ---
metric_card = """
<div style="border: 1px solid #ccc; border-radius: 5px; padding: 15px; background-color: #ffffff; text-align: center; height: 115px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
    <h2 style="margin: 0 0 5px 0; font-size: 28px; color: #222;">{value}</h2>
    <p style="margin: 0; font-size: 16px; color: #444; font-weight: bold;">{title}</p>
</div>
"""

gender_card = """
<div style="border: 1px solid #ccc; border-radius: 5px; padding: 15px; background-color: #ffffff; text-align: center; height: 115px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
    <p style="margin: 0 0 5px 0; font-size: 16px; color: #222; font-weight: bold;">TOTAL MALE: <span style="font-size: 20px;">{male_val}</span></p>
    <p style="margin: 0; font-size: 16px; color: #222; font-weight: bold;">TOTAL FEMALE: <span style="font-size: 20px;">{female_val}</span></p>
</div>
"""

middle_left_card = """
<div style="border: 1px solid #ccc; border-radius: 5px; padding: 20px; background-color: #ffffff; height: 100%; min-height: 450px; display: flex; flex-direction: column; justify-content: space-between; box-sizing: border-box;">
    <div>
        <h2 style="margin:0; font-size: 26px; color: #222;">{val1}</h2>
        <p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">Production Area (CROPS)</p>
    </div>
    <div style="margin-top: 20px;">
        <h2 style="margin:0; font-size: 26px; color: #222;">{val2}</h2>
        <p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">Production Area (FISHERIES)</p>
    </div>
    <div style="margin-top: 20px;">
        <h2 style="margin:0; font-size: 26px; color: #222;">{val3}</h2>
        <p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">TOTAL TREES</p>
    </div>
    <div style="margin-top: 20px;">
        <h2 style="margin:0; font-size: 26px; color: #222;">{val4}</h2>
        <p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">TOTAL HEADS</p>
    </div>
</div>
"""

chart_header = """
<div style="padding: 8px; text-align: center; border-bottom: 1px solid #ccc; background-color: #fafafa;">
    <p style="margin: 0; font-size: 11px; color: #222; font-weight: bold;">{title}</p>
</div>
"""

# ----------------------------------------------------
# TAB 1: DASHBOARD OVERVIEW (Filtered Data)
# ----------------------------------------------------
with dash_tab:
    if filtered_df.empty:
        st.warning("No data found matching your current filters. Try adjusting your selections.")
    else:
        clean_fca_df = filtered_df.drop_duplicates(subset=['_FCA_ID'])
        
        total_members_count = clean_fca_df["Total Members"].sum()
        total_male = clean_fca_df["Male"].sum()
        total_female = clean_fca_df["Female"].sum()
        
        total_clusters = filtered_df[get_valid_mask(filtered_df['NAME OF CLUSTER'])]['NAME OF CLUSTER'].nunique()
        total_fca_groups = clean_fca_df['_FCA_ID'].nunique()
        total_commodities = filtered_df[get_valid_mask(filtered_df['COMMODITY'])]['COMMODITY'].nunique()

        is_fishery = filtered_df['COMMODITY'].astype(str).str.contains('fishery|fish', case=False, na=False)
        crops_area = filtered_df.loc[~is_fishery, 'Production Area\n (Has.)'].sum()
        fishery_area = filtered_df.loc[is_fishery, 'Production Area\n (Has.)'].sum()

        is_tree = filtered_df['Unit (Ha/s, Head, Trees)'].astype(str).str.contains('tree', case=False, na=False)
        total_trees = filtered_df.loc[is_tree, 'Production Area\n (Trees, Heads)'].sum()
        total_heads = filtered_df.loc[~is_tree, 'Production Area\n (Trees, Heads)'].sum()

        top1, top2, top3, top4, top5 = st.columns(5)
        with top1: st.markdown(metric_card.format(value=total_clusters, title="TOTAL CLUSTER"), unsafe_allow_html=True)
        with top2: st.markdown(metric_card.format(value=f"{total_fca_groups:,.0f}", title="TOTAL FCA MEMBERS"), unsafe_allow_html=True)
        with top3: st.markdown(metric_card.format(value=total_commodities, title="CLUSTER BY COMMODITY"), unsafe_allow_html=True)
        with top4: st.markdown(metric_card.format(value=f"{total_members_count:,.0f}", title="TOTAL MEMBERS"), unsafe_allow_html=True)
        with top5: st.markdown(gender_card.format(male_val=f"{total_male:,.0f}", female_val=f"{total_female:,.0f}"), unsafe_allow_html=True)

        st.write("---") 

        mid_left, mid_right = st.columns([1, 3])

        with mid_left:
            st.write("**Production Summaries**")
            st.markdown(middle_left_card.format(
                val1=f"{crops_area:,.2f}", val2=f"{fishery_area:,.2f}", 
                val3=f"{total_trees:,.0f}", val4=f"{total_heads:,.0f}"
            ), unsafe_allow_html=True)

        with mid_right:
            st.write("**FCA & Assessment Classifications**")
            
            def make_chart(df, column_name, subset_col, is_donut=True):
                if column_name in df.columns and subset_col in df.columns:
                    valid_mask = get_valid_mask(df[subset_col])
                    clean_df = df[valid_mask].drop_duplicates(subset=[subset_col]).copy()
                    
                    clean_df[column_name] = clean_df[column_name].astype(str).str.strip().str.title()
                    clean_df = clean_df[clean_df[column_name].isin(['None', 'Nan', '']) == False]
                    clean_df = clean_df.dropna(subset=[column_name])
                    
                    if clean_df.empty: return None
                    
                    counts = clean_df[column_name].value_counts().reset_index()
                    counts.columns = [column_name, 'Count']
                    
                    fig = go.Figure()
                    hole_size = 0.6 if is_donut else 0
                    custom_colors = ['#2CA02C', '#FFD700', '#1F77B4', '#FF7F0E', '#9467BD']
                    
                    fig.add_trace(go.Pie(
                        labels=counts[column_name], values=counts['Count'], hole=hole_size,
                        textinfo='value', textposition='outside', textfont=dict(color='black', size=14),
                        marker=dict(colors=custom_colors, line=dict(color='#000000', width=1)), 
                        sort=False, direction='clockwise', showlegend=True   
                    ))
                    
                    fig.add_trace(go.Pie(
                        labels=counts[column_name], values=counts['Count'], hole=hole_size,
                        textinfo='percent', textposition='inside', insidetextfont=dict(color='black', size=14), 
                        marker=dict(colors=custom_colors, line=dict(color='#000000', width=1)), 
                        sort=False, direction='clockwise', hoverinfo='skip', showlegend=False  
                    ))

                    fig.update_layout(
                        margin=dict(t=40, b=10, l=10, r=10), height=240, showlegend=True, 
                        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, font=dict(size=10, color='black')),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color='black') 
                    )
                    return fig
                return None

            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r2c1, r2c2, r2c3, r2c4 = st.columns(4)
            
            with r1c1:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="FCA CLASSIFICATION"), unsafe_allow_html=True)
                fig_fca = make_chart(filtered_df, 'FCA Clasification\n(Association/Cooperative/Federation)', '_FCA_ID', is_donut=False)
                if fig_fca: st.plotly_chart(fig_fca, use_container_width=True, key="chart_fca")
                st.markdown('</div>', unsafe_allow_html=True)
                
            with r1c2:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="STATUS OF MOA"), unsafe_allow_html=True)
                fig_moa = make_chart(filtered_df, 'STATUS OF MEMORANDUM OF AGREEMENT (MOA)', 'NAME OF BIG-BROTHER', is_donut=True)
                if fig_moa: st.plotly_chart(fig_moa, use_container_width=True, key="chart_moa")
                st.markdown('</div>', unsafe_allow_html=True)

            with r1c3:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="STATUS OF CDP"), unsafe_allow_html=True)
                fig_cdp = make_chart(filtered_df, 'STATUS OF CDP', 'NAME OF BIG-BROTHER', is_donut=True)
                if fig_cdp: st.plotly_chart(fig_cdp, use_container_width=True, key="chart_cdp")
                st.markdown('</div>', unsafe_allow_html=True)

            with r1c4:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="CSO ACCREDITED"), unsafe_allow_html=True)
                fig_cso = make_chart(filtered_df, 'CSO ACCREDITATED\n(YES/NO)', '_FCA_ID', is_donut=False)
                if fig_cso: st.plotly_chart(fig_cso, use_container_width=True, key="chart_cso")
                st.markdown('</div>', unsafe_allow_html=True)
                
            with r2c1:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="STATUS ASSESSMENT (RICE)"), unsafe_allow_html=True)
                fig_assessment = make_chart(filtered_df, 'Status of Assessment\n(Rice)', '_FCA_ID', is_donut=True)
                if fig_assessment: st.plotly_chart(fig_assessment, use_container_width=True, key="chart_assessment")
                st.markdown('</div>', unsafe_allow_html=True)

            with r2c2:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="STATUS OF PROFILING"), unsafe_allow_html=True)
                fig_prof = make_chart(filtered_df, 'Status of Profiling', '_FCA_ID', is_donut=True)
                if fig_prof: st.plotly_chart(fig_prof, use_container_width=True, key="chart_prof")
                st.markdown('</div>', unsafe_allow_html=True)
                
            with r2c3:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="FFEDIS REGISTERED"), unsafe_allow_html=True)
                fig_ffedis = make_chart(filtered_df, 'FFEDIS Registered \n(YES/NO)', '_FCA_ID', is_donut=False)
                if fig_ffedis: st.plotly_chart(fig_ffedis, use_container_width=True, key="chart_ffedis")
                st.markdown('</div>', unsafe_allow_html=True)
                
            with r2c4:
                st.markdown('<div style="border: 1px solid #ccc; border-radius: 5px; background-color: #fff; overflow: hidden; height: 100%;">', unsafe_allow_html=True)
                st.markdown(chart_header.format(title="RCEF ACCREDITED"), unsafe_allow_html=True)
                fig_rcef = make_chart(filtered_df, 'RCEF Accredited \n(YES/NO)', '_FCA_ID', is_donut=False)
                if fig_rcef: st.plotly_chart(fig_rcef, use_container_width=True, key="chart_rcef")
                st.markdown('</div>', unsafe_allow_html=True)

        st.write("---")

        bot_left, bot_right = st.columns(2)
        
        with bot_left:
            st.write("**Demography (By Municipality)**")
            muni_grouped = filtered_df.groupby('MUNICIPALITY', as_index=False).agg(
                Area_Has=('Production Area\n (Has.)', 'sum'),
                Area_Trees=('Production Area\n (Trees, Heads)', 'sum')      
            )
            
            muni_melted = muni_grouped.melt(id_vars='MUNICIPALITY', value_vars=['Area_Has', 'Area_Trees'], var_name='Type', value_name='Area')
            muni_melted['Type'] = muni_melted['Type'].map({'Area_Has': 'Production Area (Has.)', 'Area_Trees': 'Production Area (Trees, Heads)'})
            muni_melted = muni_melted[muni_melted['Area'] > 0] 
            
            fig_demo = px.bar(
                muni_melted, x='MUNICIPALITY', y='Area', color='Type',
                barmode='group', color_discrete_map={'Production Area (Has.)': '#2CA02C', 'Production Area (Trees, Heads)': '#FFD700'}, 
                text_auto='.2s'
            ) 
            fig_demo.update_layout(
                margin=dict(t=30, b=10, l=10, r=10), height=600, legend_title_text='',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font=dict(size=10, color='black')),
                yaxis_title="", xaxis_title="Municipality", font=dict(color='black') 
            )
            fig_demo.update_yaxes(tickformat=",")
            st.plotly_chart(fig_demo, use_container_width=True, key="bar_demo")
            
        with bot_right:
            st.write("**Commodities Production Area**")
            comm_grouped = filtered_df.groupby('COMMODITY', as_index=False).agg(
                Area_Has=('Production Area\n (Has.)', 'sum'),
                Area_Trees=('Production Area\n (Trees, Heads)', 'sum')
            )
            
            comm_melted = comm_grouped.melt(id_vars='COMMODITY', value_vars=['Area_Has', 'Area_Trees'], var_name='Type', value_name='Area')
            comm_melted['Type'] = comm_melted['Type'].map({'Area_Has': 'Production Area (Has.)', 'Area_Trees': 'Production Area (Trees, Heads)'})
            comm_melted = comm_melted[comm_melted['Area'] > 0] 
            
            fig_comm = px.bar(
                comm_melted, x='COMMODITY', y='Area', color='Type',
                barmode='group', color_discrete_map={'Production Area (Has.)': '#2CA02C', 'Production Area (Trees, Heads)': '#FFD700'}, 
                text_auto='.2s'
            ) 
            fig_comm.update_layout(
                margin=dict(t=30, b=10, l=10, r=10), height=600, legend_title_text='',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font=dict(size=10, color='black')),
                yaxis_title="", xaxis_title="Commodity", font=dict(color='black') 
            )
            fig_comm.update_yaxes(tickformat=",")
            st.plotly_chart(fig_comm, use_container_width=True, key="bar_comm")


# ----------------------------------------------------
# TAB 2: PROVINCIAL BREAKDOWN (Unfiltered Base Data)
# ----------------------------------------------------
with prov_tab:
    st.write("### Provincial Breakdown")
    st.caption("*(Note: This tab shows full regional data and operates completely independently of the sidebar filters)*")
    
    provinces = sorted([str(p) for p in df['PROVINCE'].unique() if pd.notnull(p) and str(p).strip() not in ['', 'Nan', 'None']])
    
    for prov in provinces:
        with st.expander(f"📍 {prov} Breakdown", expanded=False):
            p_df = df[df['PROVINCE'] == prov]
            
            p_fca = p_df.drop_duplicates(subset=['_FCA_ID'])
            p_mems = p_fca['Total Members'].sum()
            p_clust = p_df[get_valid_mask(p_df['NAME OF CLUSTER'])]['NAME OF CLUSTER'].nunique()
            p_fca_ct = p_fca['_FCA_ID'].nunique()
            p_comm = p_df[get_valid_mask(p_df['COMMODITY'])]['COMMODITY'].nunique()
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.markdown(metric_card.format(value=p_clust, title="TOTAL CLUSTER"), unsafe_allow_html=True)
            with c2: st.markdown(metric_card.format(value=f"{p_fca_ct:,.0f}", title="TOTAL FCA MEMBERS"), unsafe_allow_html=True)
            with c3: st.markdown(metric_card.format(value=p_comm, title="CLUSTER BY COMMODITY"), unsafe_allow_html=True)
            with c4: st.markdown(metric_card.format(value=f"{p_mems:,.0f}", title="TOTAL MEMBERS"), unsafe_allow_html=True)
            
            st.write("---")
            
            p_is_fish = p_df['COMMODITY'].astype(str).str.contains('fishery|fish', case=False, na=False)
            p_crops = p_df.loc[~p_is_fish, 'Production Area\n (Has.)'].sum()
            p_fish = p_df.loc[p_is_fish, 'Production Area\n (Has.)'].sum()
            
            p_is_tree = p_df['Unit (Ha/s, Head, Trees)'].astype(str).str.contains('tree', case=False, na=False)
            p_trees = p_df.loc[p_is_tree, 'Production Area\n (Trees, Heads)'].sum()
            p_heads = p_df.loc[~p_is_tree, 'Production Area\n (Trees, Heads)'].sum()
            
            col_prod, col_class_grid = st.columns([1, 3])
            
            with col_prod:
                st.write("**Production Summaries**")
                st.markdown(f"""
                <div style="border: 1px solid #ccc; border-radius: 5px; padding: 20px; background-color: #ffffff; height: 775px; display: flex; flex-direction: column; justify-content: space-between; box-sizing: border-box;">
                    <div><h2 style="margin:0; font-size: 26px; color: #222;">{p_crops:,.2f}</h2><p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">Production Area (CROPS)</p></div>
                    <div style="margin-top: 20px;"><h2 style="margin:0; font-size: 26px; color: #222;">{p_fish:,.2f}</h2><p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">Production Area (FISHERIES)</p></div>
                    <div style="margin-top: 20px;"><h2 style="margin:0; font-size: 26px; color: #222;">{p_trees:,.0f}</h2><p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">TOTAL TREES</p></div>
                    <div style="margin-top: 20px;"><h2 style="margin:0; font-size: 26px; color: #222;">{p_heads:,.0f}</h2><p style="margin:0; font-size: 15px; color: #555; font-weight: bold;">TOTAL HEADS</p></div>
                </div>
                """, unsafe_allow_html=True)
                
            with col_class_grid:
                st.write("**FCA & Assessment Classifications**")
                r1c1, r1c2, r1c3, r1c4 = st.columns(4)
                r2c1, r2c2, r2c3, r2c4 = st.columns(4)
                
                with r1c1: st.markdown(get_text_card("FCA CLASSIFICATION", p_df, 'FCA Clasification\n(Association/Cooperative/Federation)', '_FCA_ID'), unsafe_allow_html=True)
                with r1c2: st.markdown(get_text_card("STATUS OF MOA", p_df, 'STATUS OF MEMORANDUM OF AGREEMENT (MOA)', 'NAME OF BIG-BROTHER'), unsafe_allow_html=True)
                with r1c3: st.markdown(get_text_card("STATUS OF CDP", p_df, 'STATUS OF CDP', 'NAME OF BIG-BROTHER'), unsafe_allow_html=True)
                with r1c4: st.markdown(get_text_card("CSO ACCREDITED", p_df, 'CSO ACCREDITATED\n(YES/NO)', '_FCA_ID'), unsafe_allow_html=True)
                
                st.write("<br>", unsafe_allow_html=True)
                
                with r2c1: st.markdown(get_text_card("STATUS ASSESSMENT (RICE)", p_df, 'Status of Assessment\n(Rice)', '_FCA_ID'), unsafe_allow_html=True)
                with r2c2: st.markdown(get_text_card("STATUS OF PROFILING", p_df, 'Status of Profiling', '_FCA_ID'), unsafe_allow_html=True)
                with r2c3: st.markdown(get_text_card("FFEDIS REGISTERED", p_df, 'FFEDIS Registered \n(YES/NO)', '_FCA_ID'), unsafe_allow_html=True)
                with r2c4: st.markdown(get_text_card("RCEF ACCREDITED", p_df, 'RCEF Accredited \n(YES/NO)', '_FCA_ID'), unsafe_allow_html=True)


# ----------------------------------------------------
# TAB 3: NEW CDP PROFILE (Completely Independent)
# ----------------------------------------------------
with cdp_tab:
    st.write("### CDP Profile")
    st.caption("*(Note: This tab uses its own filters below and operates independently from the main dashboard)*")
    
    cdp_filtered = df_cdp.copy()
    
    # --- 1. INDEPENDENT CDP FILTERS ---
    fc1, fc2, fc3, fc4 = st.columns(4)
    
    with fc1:
        if 'COMMODITY / SERVICES' in cdp_filtered.columns:
            opts_comm = ["All"] + sorted([str(x) for x in cdp_filtered['COMMODITY / SERVICES'].dropna().unique() if str(x).strip() != ""])
            cdp_comm = st.selectbox("Commodity / Services:", opts_comm, key="cdp_comm")
            if cdp_comm != "All":
                cdp_filtered = cdp_filtered[cdp_filtered['COMMODITY / SERVICES'] == cdp_comm]
                
    with fc2:
        if 'PROGRAM /ACTIVITIES / PROJECTS' in cdp_filtered.columns:
            opts_prog = ["All"] + sorted([str(x) for x in cdp_filtered['PROGRAM /ACTIVITIES / PROJECTS'].dropna().unique() if str(x).strip() != ""])
            cdp_prog = st.selectbox("Program / Activities / Projects:", opts_prog, key="cdp_prog")
            if cdp_prog != "All":
                cdp_filtered = cdp_filtered[cdp_filtered['PROGRAM /ACTIVITIES / PROJECTS'] == cdp_prog]
                
    with fc3:
        if 'TYPE OF INTERVENTION' in cdp_filtered.columns:
            opts_interv = ["All"] + sorted([str(x) for x in cdp_filtered['TYPE OF INTERVENTION'].dropna().unique() if str(x).strip() != ""])
            cdp_interv = st.selectbox("Type of Intervention:", opts_interv, key="cdp_interv")
            if cdp_interv != "All":
                cdp_filtered = cdp_filtered[cdp_filtered['TYPE OF INTERVENTION'] == cdp_interv]
                
    with fc4:
        # Years logic: If user selects a specific year, keep only rows where that year is NOT blank
        year_options = ["All Years", "YEAR 1", "YEAR 2", "YEAR 3", "YEAR 4", "YEAR 5"]
        cdp_year = st.selectbox("Year:", year_options, key="cdp_year")
        if cdp_year != "All Years" and cdp_year in cdp_filtered.columns:
            cdp_filtered = cdp_filtered[get_valid_mask(cdp_filtered[cdp_year])]

    # Independent Universal Search for CDP
    st.write("") # Spacer
    master_cdp_search = pd.concat([cdp_filtered[c] for c in cdp_filtered.columns]).dropna().unique()
    opts_cdp_search = [""] + sorted([str(x) for x in master_cdp_search if str(x).strip() != ""])
    cdp_search_query = st.selectbox("Search CDP Data (Type or Select):", opts_cdp_search, key="cdp_search")
    
    if cdp_search_query != "":
        search_val_cdp = str(cdp_search_query).strip().lower()
        mask_cdp = cdp_filtered.astype(str).apply(lambda x: x.str.strip().str.lower() == search_val_cdp).any(axis=1)
        cdp_filtered = cdp_filtered[mask_cdp]

    st.write("---")

    if cdp_filtered.empty:
        st.warning("No data found matching your CDP filters.")
    else:
        # --- 2. CHARTS ---
        ch1, ch2 = st.columns([1, 2])
        
        with ch1:
            st.write("**Commodity / Services Breakdown**")
            if 'COMMODITY / SERVICES' in cdp_filtered.columns:
                pie_counts = cdp_filtered['COMMODITY / SERVICES'].value_counts().reset_index()
                pie_counts.columns = ['COMMODITY / SERVICES', 'Count']
                
                custom_colors = ['#2CA02C', '#FFD700', '#1F77B4', '#FF7F0E', '#9467BD']
                
                fig_cdp_pie = px.pie(pie_counts, names='COMMODITY / SERVICES', values='Count', hole=0.6,
                                     color_discrete_sequence=custom_colors)
                fig_cdp_pie.update_traces(textinfo='value', textfont=dict(color='black', size=14), 
                                          marker=dict(line=dict(color='#000000', width=1)))
                fig_cdp_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True, height=400,
                                          legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, font=dict(color='black')),
                                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color='black'))
                st.plotly_chart(fig_cdp_pie, use_container_width=True, key="cdp_pie_chart")
                
        with ch2:
            st.write("**Interventions Count per Year by Province**")
            years = ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5']
            exist_years = [y for y in years if y in cdp_filtered.columns]
            
            if 'PROVINCE' in cdp_filtered.columns and exist_years:
                # Melt data to group by Province and Year
                cdp_melted = cdp_filtered.melt(id_vars='PROVINCE', value_vars=exist_years, var_name='Year', value_name='Value')
                
                # Convert values to numeric for proper summing
                cdp_melted['Value'] = pd.to_numeric(cdp_melted['Value'].astype(str).str.replace(',', '', regex=False), errors='coerce').fillna(0)
                
                # Drop rows where the specific Year column was 0 or blank
                cdp_melted = cdp_melted[cdp_melted['Value'] > 0]
                
                # SUM valid occurrences per Province per Year instead of just counting rows
                cdp_grouped = cdp_melted.groupby(['Year', 'PROVINCE'])['Value'].sum().reset_index(name='Total Count')
                
                # NEW: Dynamically set the X-axis title to the active Province(s) being displayed
                active_provs = cdp_grouped['PROVINCE'].dropna().unique()
                x_axis_title = ", ".join(active_provs) if len(active_provs) > 0 else "Province"
                
                fig_cdp_bar = px.bar(
                    cdp_grouped, x='Year', y='Total Count', color='PROVINCE', barmode='group',
                    text_auto='.0f', color_discrete_sequence=['#2CA02C', '#FFD700', '#1F77B4', '#FF7F0E', '#9467BD']
                )
                fig_cdp_bar.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10), height=400,
                    xaxis_title=x_axis_title, yaxis_title="Total Interventions",
                    legend_title_text="Province", font=dict(color='black'),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig_cdp_bar, use_container_width=True, key="cdp_bar_chart")
                
        st.write("---")
        
        # --- 3. DATA TABLE ---
        st.write("**CDP Profile Data Table**")
        req_cols = ['PROVINCE', 'NAME OF CLUSTER', 'NAME OF MEMBER FCA \n(Requesting FCA)', 'COMMODITY / SERVICES', 'TYPE OF INTERVENTION', 'TOTAL QUANTITY', 'FUND SOURCE']
        disp_cols = [c for c in req_cols if c in cdp_filtered.columns]
        
        st.dataframe(cdp_filtered[disp_cols], use_container_width=True, hide_index=True)


# ------------------------------------------
# TAB 4: SYSTEM DATA TABLES (OPTIMIZED EXPORT)
# ------------------------------------------
with table_tab:
    if filtered_df.empty:
        st.warning("No data found matching your current filters. Try adjusting your selections.")
    else:
        st.write("### Master Data Tables")
        
        def get_existing_cols(df, desired_cols):
            return [col for col in desired_cols if col in df.columns]

        t1_cols = get_existing_cols(filtered_df, ['NAME OF CLUSTER', 'NAME OF BIG-BROTHER', 'TOTAL FCA MEMBER', 'YEAR OF ESTABLISHMENT', 'CLUSTER BY COMMODITY', 'STATUS OF MEMORANDUM OF AGREEMENT (MOA)', 'STATUS OF CDP'])
        table1 = filtered_df.drop_duplicates(subset=['NAME OF CLUSTER', 'NAME OF BIG-BROTHER'])[t1_cols]

        t2_cols = get_existing_cols(filtered_df, ['NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'Total Members', 'Contact Number', 'PROVINCE', 'MUNICIPALITY', 'BARANGAY', 'Contact Person', 'Status of Profiling'])
        table2 = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t2_cols]

        t3_cols = get_existing_cols(filtered_df, ['NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'Total Assets', 'Primary Activity\n(ex.Producer, Processor, Capitalization, Marketing[Buy and Sell], Producer of Meat/Poultry, Consolidator, farm/Agricultural Supply)'])
        t3_cols.extend([col for col in filtered_df.columns if "Classification based on the Asset" in col])
        t3_cols.extend([col for col in filtered_df.columns if "Classification based on the HARMONIZED" in col])
        table3 = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t3_cols]

        t4_cols = get_existing_cols(filtered_df, ['Registration\n(CDA/SEC/DOLE/DSWD)', 'NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'Date of Registration', 'Registration Number', 'STATUS OF REGISTRATION\n(Active or Not Active)'])
        table4 = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t4_cols]
        
        t5a_cols = get_existing_cols(filtered_df, ['CSO ACCREDITATED\n(YES/NO)', 'NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'CSO Date of Accreditation \n(Month-Year)', 'CSO Accreditation Number', 'VALIDITY'])
        table5a = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t5a_cols]

        t5b_cols = get_existing_cols(filtered_df, ['FFEDIS Registered \n(YES/NO)', 'NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'FFEDIS Registration Date \n(Month-Year)', 'FFEDIS Reg No. ', 'STATUS OF FFEDIS REGISTRATION\n(Active or Not Active)'])
        table5b = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t5b_cols]

        t5c_cols = get_existing_cols(filtered_df, ['RCEF Accredited \n(YES/NO)', 'NAME OF CLUSTER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'RCEF Date of Accredition\n(Month-Year)', 'RCEF Accreditation No.', 'Other Accrediation '])
        table5c = filtered_df.drop_duplicates(subset=['_FCA_ID'])[t5c_cols]

        t5d_cols = get_existing_cols(filtered_df, ['NAME OF CLUSTER', 'NAME OF BIG-BROTHER', 'NAME OF FCA MEMBERS', 'PROVINCE', 'MUNICIPALITY', 'BARANGAY', 'COMMODITY CATEGORY', 'COMMODITY', 'TYPE COMMODITY', 'Status of Assessment\n(Rice)',  'Production Area\n (Has.)', 'Production Area\n (Trees, Heads)', 'Unit (Ha/s, Head, Trees)'])
        table5d = filtered_df[t5d_cols].drop_duplicates()
        
        # Add CDP Table to exports
        cdp_export_cols = [c for c in ['PROVINCE', 'NAME OF CLUSTER', 'NAME OF MEMBER FCA \n(Requesting FCA)', 'COMMODITY / SERVICES', 'PROGRAM /ACTIVITIES / PROJECTS', 'TYPE OF INTERVENTION', 'TOTAL QUANTITY', 'FUND SOURCE', 'YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'] if c in df_cdp.columns]
        table_cdp = df_cdp[cdp_export_cols]

        @st.cache_data(show_spinner=False)
        def generate_excel_report(df_hash, cdp_hash):
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                workbook = writer.book
                worksheet = workbook.add_worksheet('System Reports')
                writer.sheets['System Reports'] = worksheet
                
                title_format = workbook.add_format({'bold': True, 'font_size': 12})
                current_row = 0
                
                def write_table_to_sheet(df_sheet, title, row_index):
                    worksheet.write_string(row_index, 0, title, title_format)
                    row_index += 2 
                    if not df_sheet.empty:
                        df_sheet.to_excel(writer, sheet_name='System Reports', startrow=row_index, index=False)
                        row_index += len(df_sheet) + 3 
                    else:
                        df_sheet.to_excel(writer, sheet_name='System Reports', startrow=row_index, index=False)
                        row_index += 4 
                    return row_index 
                        
                current_row = write_table_to_sheet(table1, "Table 1: CLUSTER PROFILE", current_row)
                current_row = write_table_to_sheet(table2, "Table 2: FCA PROFILE", current_row)
                current_row = write_table_to_sheet(table3, "Table 3: FCA FINANCIAL AND CAPACITY LEVEL", current_row)
                current_row = write_table_to_sheet(table4, "Table 4: FCA REGISTRATION", current_row)
                current_row = write_table_to_sheet(table5a, "Table 5A: FCA CSO ACCREDITATION", current_row)
                current_row = write_table_to_sheet(table5b, "Table 5B: FCA FFEDIS REGISTRATION", current_row)
                current_row = write_table_to_sheet(table5c, "Table 5C: FCA RCEF ACCREDITATION AND OTHERS", current_row)
                current_row = write_table_to_sheet(table5d, "Table 5D: FCA COMMODITY PROFILE", current_row)
                current_row = write_table_to_sheet(table_cdp, "Table 6: CDP PROFILE", current_row)
            return buffer.getvalue()

        # Pass a hash reference so the cache perfectly updates when filters change
        excel_data = generate_excel_report(len(filtered_df), len(df_cdp))

        st.download_button(
            label=" Download All Table Reports (Excel)",
            data=excel_data,
            file_name="All_Table_Reports.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        st.divider()

        st.write("**Table 1: CLUSTER PROFILE**")
        st.dataframe(table1, use_container_width=True, hide_index=True)

        st.write("**Table 2: FCA Profile**")
        st.dataframe(table2, use_container_width=True, hide_index=True)

        st.write("**Table 3: FCA Financial and Capacity Level**")
        st.dataframe(table3, use_container_width=True, hide_index=True)

        st.write("**Table 4: FCA Registration**")
        st.dataframe(table4, use_container_width=True, hide_index=True)
        
        st.write("**Table 5A: FCA CSO Accreditation**")
        st.dataframe(table5a, use_container_width=True, hide_index=True)

        st.write("**Table 5B: FCA FFEDIS Registration**")
        st.dataframe(table5b, use_container_width=True, hide_index=True)

        st.write("**Table 5C: FCA RCEF Accreditation and Others**")
        st.dataframe(table5c, use_container_width=True, hide_index=True)

        st.write("**Table 5D: FCA Commodity Profile**")
        st.dataframe(table5d, use_container_width=True, hide_index=True)
