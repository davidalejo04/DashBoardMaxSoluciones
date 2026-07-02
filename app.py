import streamlit as st
import pandas as pd
import pyodbc
import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Dashboard de Asignación DB", layout="wide")
st.title("🗓️ Dashboard de Asignación de Labores (Conexión SQL Server)")

# =============================================================================
# 1. CONFIGURACIÓN DE CONEXIÓN (SEGURO DESDE SECRETS)
# =============================================================================
# Streamlit busca automáticamente en .streamlit/secrets.toml (local) 
# o en la nube de Streamlit Cloud (producción)
CONN_STR = st.secrets["CONN_STR"]

def ejecutar_query(query, params=None, commit=False):
    """Función utilitaria para manejar la conexión y consultas."""
    with pyodbc.connect(CONN_STR) as conn:
        with conn.cursor() as cursor:
            if commit:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                conn.commit()
                return True
            else:
                return pd.read_sql(query, conn)

# --- DICCIONARIO DE COLORES PARA NOVEDADES ---
COLOR_MAP = {
    'NORMAL': '#d4edda',   # Verde claro (Sin Novedad)
    'D001': '#e2e3e5',     # Gris (Descanso)
    'I002': '#f8d7da',     # Rojo claro (Incapacidad)
    'CF003': '#fff3cd',    # Amarillo claro (Calamidad Familiar)
    'PNR04': '#ffeeba',    # Naranja claro (Permiso no remunerado)
    'AU005': '#f5c6cb',    # Rojo fuerte (Ausencia)
    'VA006': '#cce5ff',    # Azul claro (Vacaciones)
    'SU007': '#d6d8db'     # Gris oscuro (Suspensión)
}
DEFAULT_COLOR = '#e8daef'  # Morado claro para otras novedades no mapeadas

# --- 2. CARGA DE DATOS DESDE LA DB ---
@st.cache_data(ttl=600)  # Caché de 10 minutos para no saturar la DB
def cargar_datos_db():
    try:
        # Query centralizado con todos los JOINs necesarios
        query_principal = """
            SELECT 
                p.ID_Empleado,
                e.Empleado_Nam,
                p.ID_Unidad,
                u.Unidad_Desc,
                p.Fecha,
                p.ID_Turno,
                t.Punch_In,
                t.Punch_Out,
                ej.ID_Novedad
            FROM Programacion p
            LEFT JOIN N_Empleados e ON TRIM(p.ID_Empleado) = TRIM(e.ID_Empleado)
            LEFT JOIN N_Unidades u ON TRIM(p.ID_Unidad) = TRIM(u.ID_Unidad)
            LEFT JOIN N_Turnos t ON TRIM(p.ID_Turno) = TRIM(t.ID_Turno)
            LEFT JOIN Ejecucion ej ON TRIM(p.ID_Empleado) = TRIM(ej.ID_Empleado) 
                                  AND TRIM(p.ID_Unidad) = TRIM(ej.ID_Unidad) 
                                  AND p.Fecha = ej.Fecha
                                  AND TRIM(p.ID_Turno) = TRIM(ej.ID_Turno)
        """
        df_completo = ejecutar_query(query_principal)
        
        # Cargar catálogo de novedades para la leyenda
        query_novedades = "SELECT ID_Novedad, Novedad_Desc FROM N_Novedades"
        df_nov = ejecutar_query(query_novedades)
        
        # Procesamiento de fechas en Pandas
        df_completo['Fecha'] = pd.to_datetime(df_completo['Fecha'])
        df_completo['Semana'] = df_completo['Fecha'].dt.isocalendar().week
        df_completo['Dia_Nombre'] = df_completo['Fecha'].dt.day_name().map({
            'Monday': '1-Lunes', 'Tuesday': '2-Martes', 'Wednesday': '3-Miércoles',
            'Thursday': '4-Jueves', 'Friday': '5-Viernes', 'Saturday': '6-Sábado', 'Sunday': '7-Domingo'
        })
        
        return df_completo, df_nov
    except Exception as e:
        st.error(f"⚠️ Error al conectar o consultar la Base de Datos: {e}")
        return pd.DataFrame(), pd.DataFrame()

# Cargar la información
df, df_novedades = cargar_datos_db()

if df.empty:
    st.warning("No se pudieron extraer datos de la base de datos o las tablas están vacías.")
    st.stop()

# --- FUNCIÓN EXTRACTORA DE HORAS (SOPORTA STR Y OBJETOS TIME) ---
def expandir_horas(row):
    try:
        def parse_hora(val):
            if isinstance(val, datetime.time):
                return val.hour
            return int(str(val).split(':')[0])

        start_h = parse_hora(row['Punch_In'])
        end_h = parse_hora(row['Punch_Out'])
        
        if end_h <= start_h:
            end_h += 24  # Manejo de turnos nocturnos cruzados
            
        return [f"{h % 24:02d}:00" for h in range(start_h, end_h)]
    except:
        return []

# --- 3. SIDEBAR: FILTROS INTERACTIVOS ---
st.sidebar.header("Filtros del Dashboard")

semanas_disponibles = sorted(df['Semana'].dropna().unique())
semana_seleccionada = st.sidebar.selectbox("Seleccione el Número de Semana", semanas_disponibles)

vista_seleccionada = st.sidebar.radio(
    "Seleccione Modalidad de Visualización",
    ("1. Por Trabajador (Ver Unidades)", "2. Por Unidad (Ver Trabajadores)")
)

# Filtrar base por la semana seleccionada
df_semana = df[df['Semana'] == semana_seleccionada].copy()

if "Por Trabajador" in vista_seleccionada:
    lista_empleados = sorted(df_semana['Empleado_Nam'].dropna().unique())
    entidad_seleccionada = st.sidebar.selectbox("Seleccione el Trabajador", lista_empleados)
    df_filtrado = df_semana[df_semana['Empleado_Nam'] == entidad_seleccionada]
    col_a_mostrar = 'Unidad_Desc'
else:
    lista_unidades = sorted(df_semana['Unidad_Desc'].dropna().unique())
    entidad_seleccionada = st.sidebar.selectbox("Seleccione la Unidad", lista_unidades)
    df_filtrado = df_semana[df_semana['Unidad_Desc'] == entidad_seleccionada]
    col_a_mostrar = 'Empleado_Nam'

# --- 4. CONSTRUCCIÓN DE LA MATRIZ CALENDARIO ---
if not df_filtrado.empty:
    # Expandir horas asignadas
    df_filtrado['Hora'] = df_filtrado.apply(expandir_horas, axis=1)
    df_horario = df_filtrado.explode('Hora').dropna(subset=['Hora'])

    if not df_horario.empty:
        # Generar texto de la celda incluyendo novedad si existe
        def construir_celda(row):
            texto = str(row[col_a_mostrar])
            if pd.notna(row['ID_Novedad']) and str(row['ID_Novedad']).strip() != '':
                texto += f" [{row['ID_Novedad'].strip()}]"
            return texto

        df_horario['Celda_Texto'] = df_horario.apply(construir_celda, axis=1)
        df_horario['Color_Celda'] = df_horario['ID_Novedad'].apply(
            lambda x: COLOR_MAP.get(str(x).strip(), DEFAULT_COLOR) if pd.notna(x) else COLOR_MAP['NORMAL']
        )

        # Crear tablas pivote paralelas (una para texto, otra para color)
        pivot_text = df_horario.pivot_table(index='Hora', columns='Dia_Nombre', values='Celda_Texto', aggfunc=lambda x: ' / '.join(set(x)))
        pivot_color = df_horario.pivot_table(index='Hora', columns='Dia_Nombre', values='Color_Celda', aggfunc='first')

        # Reindexar para garantizar filas de 24 horas y columnas de 7 días completas
        horas_dia = [f"{h:02d}:00" for h in range(24)]
        dias_semana = ['1-Lunes', '2-Martes', '3-Miércoles', '4-Jueves', '5-Viernes', '6-Sábado', '7-Domingo']
        
        pivot_text = pivot_text.reindex(index=horas_dia, columns=dias_semana).fillna('')
        pivot_color = pivot_color.reindex(index=horas_dia, columns=dias_semana).fillna('')

        # === ¡AQUÍ ESTÁ EL CAMBIO! ===
        # Limpiamos los nombres de los días en AMBOS DataFrames para que coincidan perfectamente
        columnas_limpias = [c.split('-')[1] for c in pivot_text.columns]
        pivot_text.columns = columnas_limpias
        pivot_color.columns = columnas_limpias
        # =============================

        # Estilizar el DataFrame usando Pandas Styler
        def aplicar_estilos_matriz(x):
            # Usamos map (o applymap en versiones antiguas de pandas) para generar los estilos CSS
            if hasattr(pivot_color, 'map'):
                return pivot_color.fillna('').map(lambda color: f'background-color: {color}; color: #222; font-weight: bold;' if color else '')
            else:
                return pivot_color.fillna('').applymap(lambda color: f'background-color: {color}; color: #222; font-weight: bold;' if color else '')

        st.subheader(f"📅 Agenda: {entidad_seleccionada} — Semana {semana_seleccionada}")
        
        df_estilizado = pivot_text.style.apply(aplicar_estilos_matriz, axis=None)
        st.dataframe(df_estilizado, use_container_width=True, height=650)
    else:
        st.info("El turno asignado no cuenta con horas válidas configuradas en la tabla de turnos.")
else:
    st.warning("No se encontraron registros de asignación para los filtros seleccionados.")

# --- 5. LEYENDA DINÁMICA DE NOVEDADES ---
st.markdown("---")
st.markdown("### 🎨 Código de Colores y Novedades")
columnas_leyenda = st.columns(4)

# Incluir la opción por defecto 'NORMAL'
lista_leyenda = [('NORMAL', 'Programación Normal (Sin Novedad)')]
for r in df_novedades.itertuples():
    lista_leyenda.append((str(r.ID_Novedad).strip(), str(r.Novedad_Desc)))

for idx, (cod_nov, desc_nov) in enumerate(lista_leyenda):
    color_hex = COLOR_MAP.get(cod_nov, DEFAULT_COLOR)
    col = columnas_leyenda[idx % 4]
    col.markdown(
        f"<div style='background-color: {color_hex}; padding: 8px; border-radius: 6px; text-align: center; margin-bottom: 8px; border: 1px solid #ccc; color: #111; font-size: 13px;'>"
        f"<strong>{cod_nov}</strong>: {desc_nov}</div>", 
        unsafe_allow_html=True
    )
