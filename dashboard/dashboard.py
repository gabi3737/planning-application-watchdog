"""
Enhanced Planning Application Watchdog Dashboard v2
Features:
- Loads all planning applications from 3 council areas at startup (no radius dependency)
- Displays area-summary metrics at the top
- Interactive folium map with marker clustering, toggleable layers, and search/filtering
- Sidebar controls for filtering by area, type, status, date range, and address/UID search
"""
import os
import logging
import re
from datetime import datetime, timedelta
import streamlit as st
import altair as alt
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import pandas as pd
from data_functions import (
    load_application_data,
    get_sites,
    get_conservation_areas,
    APP_TYPE_COLORS,
    create_boto3_session,
    calculate_distance,
    get_postcode_coordinates,
)
from dynamodb_functions import subscribe_user

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


PATH = os.path.dirname(os.path.abspath(__file__))
LOGO_NO_BG = os.path.join(PATH, "assets/TerraNotice_NoBackground.png")
LOGO_TRANSPARENT = os.path.join(PATH, "assets/TerraNotice_Transparent.png")

# ==================== STREAMLIT PAGE CONFIG ====================
st.set_page_config(
    page_title="TerraNotice",
    page_icon=LOGO_TRANSPARENT,
    layout="wide",
    initial_sidebar_state="expanded"
)


def display_title():
    col_logo, col_title = st.columns([1, 10], gap=0)
    with col_logo:
        st.image(LOGO_NO_BG, width=70)
    with col_title:
        st.title("TerraNotice")


# ==================== UTILITY FUNCTIONS ====================

VALID_FOLIUM_COLORS = {
    "red", "blue", "gray", "darkred", "lightred",
    "orange", "beige", "green", "darkgreen", "lightgreen",
    "purple", "darkpurple", "pink",
    "cadetblue", "darkblue", "lightblue",
    "white", "black", "lightgray"
}


def map_app_type_to_folium_color(app_type: str) -> str:
    """Map application type to a valid folium icon color."""
    color = APP_TYPE_COLORS.get(app_type, "gray")
    # If color is not valid, map it to the closest valid color
    if color not in VALID_FOLIUM_COLORS:
        color_mapping = {
            "yellow": "orange",
            "darkblue": "cadetblue",
            "darkgreen": "green",
        }
        color = color_mapping.get(color, "gray")
    return color


def find_nearby_heritage_sites(lat: float, lon: float, heritage_sites: list, radius_meters: float = 100) -> list:
    """Find heritage sites within a specified radius of a given coordinate."""
    nearby_sites = []
    for site in heritage_sites:
        try:
            if "geometry" in site and "points" in site["geometry"]:
                points = site["geometry"]["points"]
                if points and len(points) > 0:
                    site_lon, site_lat = points[0][0], points[0][1]
                    distance = calculate_distance(lat, lon, site_lat, site_lon)
                    if distance <= radius_meters:
                        nearby_sites.append({
                            "distance": distance,
                            "site": site
                        })
        except Exception as err:
            logger.debug(f"Error checking heritage site proximity: {err}")
            continue

    # Sort by distance
    nearby_sites.sort(key=lambda x: x["distance"])
    return nearby_sites

# ==================== AREA ASSIGNMENT (for heritage/conservation charts) ====================


# Regional council centers, used as query origins to fetch heritage sites/conservation
# areas per council area (they have no "area" field of their own in the source data).
AREA_CENTERS = {
    "Tower Hamlets": (51.52, -0.04),
    "Newham": (51.54, 0.02),
    "Greenwich": (51.47, -0.01),
}


def get_geometry_representative_point(geometry: dict):
    """Extract a representative (lat, lon) point from an esri-json or GeoJSON geometry."""
    if not geometry:
        return None
    try:
        # Esri-JSON heritage site geometry: {"points": [[lon, lat], ...]}
        if "points" in geometry:
            lon, lat = geometry["points"][0][0], geometry["points"][0][1]
            return lat, lon

        # GeoJSON conservation area geometry: {"type": ..., "coordinates": [...]}
        gtype = geometry.get("type")
        coords = geometry.get("coordinates")
        if gtype == "Polygon":
            lon, lat = coords[0][0][0], coords[0][0][1]
            return lat, lon
        if gtype == "MultiPolygon":
            lon, lat = coords[0][0][0][0], coords[0][0][0][1]
            return lat, lon
    except (TypeError, IndexError, KeyError):
        return None
    return None


def build_heritage_conservation_counts(selected_areas: list) -> pd.DataFrame:
    """Count heritage sites and conservation areas per council area, for a stacked bar chart."""
    heritage_df = load_heritage_sites_per_area()
    conservation_df = load_conservation_areas_per_area()
    combined_df = pd.concat([heritage_df, conservation_df], ignore_index=True)

    if selected_areas:
        combined_df = combined_df[combined_df["area"].isin(selected_areas)]

    if combined_df.empty:
        return pd.DataFrame(columns=["area", "site_type", "count"])

    counts_df = combined_df.groupby(
        ["area", "site_type"]).size().reset_index(name="count")
    return counts_df


# ==================== WORKSPACE CHART BUILDERS ====================

# Light-green palette for the workspace charts (donut chart keeps STATUS_COLOR_MAP colors)
CHART_LIGHT_GREEN = "#5FCB5F"
CHART_GREEN_SHADES = "#18B020"


def build_applications_per_area_chart(df: pd.DataFrame):
    """Build a horizontal bar chart of application counts per council area."""
    if df.empty:
        return None

    counts_df = df["area"].value_counts().reset_index()
    counts_df.columns = ["area", "count"]

    chart = alt.Chart(counts_df).mark_bar(color=CHART_LIGHT_GREEN, cornerRadiusTopRight=20,
                                          cornerRadiusBottomRight=20).encode(
        x=alt.X("count:Q", title="Number of Applications"),
        y=alt.Y("area:N", title="Council Area", sort="-x"),
        tooltip=["area", "count"]
    ).properties(height=250)

    return chart


def build_status_donut_chart(df: pd.DataFrame):
    """Build a donut chart of application statuses."""
    if df.empty:
        return None

    counts_df = df["app_state"].value_counts().reset_index()
    counts_df.columns = ["status", "count"]

    # Fixed domain/range (reusing STATUS_COLOR_MAP) keeps colors stable across filters
    status_domain = list(STATUS_COLOR_MAP.keys())
    status_range = list(STATUS_COLOR_MAP.values())

    chart = alt.Chart(counts_df).mark_arc(innerRadius=70).encode(
        theta=alt.Theta("count:Q"),
        color=alt.Color("status:N", title="Status", scale=alt.Scale(
            domain=status_domain, range=status_range)),
        tooltip=["status", "count"]
    ).properties(height=300)

    return chart


def build_heritage_bar_chart():
    """Build two bar charts of heritage and conservation site counts per area, split within each bar."""
    # counts_df = build_heritage_conservation_counts(selected_areas)
    heritage_df = load_heritage_sites_per_area()
    counts_df = heritage_df["area"].value_counts().reset_index()
    counts_df.columns = ["area", "count"]

    if heritage_df.empty:
        return None

    # site_type_domain = ["Heritage Site", "Conservation Area"]

    chart = alt.Chart(counts_df).mark_bar(cornerRadiusTopRight=50, cornerRadiusTopLeft=50).encode(
        x=alt.X("area:N", title="Council Area"),
        y=alt.Y("count:Q", title="Number of Heritage Sites"),
        color=alt.Color("area:N", title="Council Area", scale=alt.Scale(
            domain=counts_df["area"].tolist(), range=[CHART_LIGHT_GREEN]), legend=None),
        tooltip=["area", "count"]
    )

    return chart


def build_conservation_bar_chart():
    """Build a bar chart of conservation area counts per area."""
    conservation_df = load_conservation_areas_per_area()
    counts_df = conservation_df["area"].value_counts().reset_index()
    counts_df.columns = ["area", "count"]

    if conservation_df.empty:
        return None

    chart = alt.Chart(counts_df).mark_bar(cornerRadiusTopRight=50, cornerRadiusTopLeft=50).encode(
        x=alt.X("area:N", title="Council Area"),
        y=alt.Y("count:Q", title="Number of Conservation Areas"),
        color=alt.Color("area:N", title="Council Area", scale=alt.Scale(
            domain=counts_df["area"].tolist(), range=[CHART_GREEN_SHADES]), legend=None),
        tooltip=["area", "count"]
    )

    return chart


def build_type_chart_per_area(df: pd.DataFrame):
    """Build a pie chart of application types per area."""
    if df.empty:
        return None

    counts_df = df["app_type"].value_counts().reset_index()
    counts_df.columns = ["app_type", "count"]

    chart = alt.Chart(counts_df).mark_arc(innerRadius=70).encode(
        theta=alt.Theta("count:Q"),
        color=alt.Color("app_type:N", title="Application Type"),
        tooltip=["app_type", "count"]
    ).properties(height=300)

    return chart


# ==================== DATA LOADING & CACHING ====================


@st.cache_data(ttl=3600)  # Refresh every hour
def load_all_applications():
    """Load all planning applications from DynamoDB across all 3 council areas."""
    try:
        session = create_boto3_session()
        df = load_application_data(session)

        if df.empty:
            logger.warning("No planning applications loaded from DynamoDB")
            return pd.DataFrame()

        # Ensure required columns exist
        required_cols = ["uid", "address", "app_type",
                         "app_state", "location_x", "location_y", "start_date", "area"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Missing columns in DataFrame: {missing_cols}")
            for col in missing_cols:
                df[col] = None

        # Log areas found
        area_counts = df["area"].value_counts()
        logger.info(
            f"Loaded {len(df)} planning applications - Areas: {area_counts.to_dict()}")
        return df

    except Exception as err:
        logger.error(f"Error loading applications: {err}")
        st.error(
            "❌ Unable to load planning applications. Please check your AWS configuration.")
        return pd.DataFrame()


@st.cache_data(ttl=86400)  # Refresh daily
def load_heritage_sites():
    """Load all heritage sites for the 3-council region (no radius dependency)."""
    try:
        # Use regional center coordinates for the 3 London boroughs
        # Tower Hamlets (51.52, -0.04), Newham (51.54, 0.02), Greenwich (51.47, -0.01)
        # Regional center approximately: (51.51, -0.01)

        # Fetch within a large radius to cover all 3 areas (~15km radius to be safe)
        heritage_sites = get_sites(
            latitude=51.51, longitude=-0.01, radius=20000)
        logger.info(f"Loaded {len(heritage_sites)} heritage sites")
        return heritage_sites

    except Exception as err:
        logger.error(f"Error loading heritage sites: {err}")
        return []


@st.cache_data(ttl=86400)  # Refresh daily
def load_conservation_areas_data():
    """Load all conservation areas for the 3-council region (no radius dependency)."""
    try:
        logger.debug(
            "🔍 [CONSERV_AREA] Starting to load conservation areas from API...")
        # Use same regional center as heritage sites
        conservation_areas = get_conservation_areas(
            latitude=51.51, longitude=-0.01, radius=5000)
        logger.info(
            f"✅ [CONSERV_AREA] Loaded {len(conservation_areas)} conservation areas")
        logger.debug(
            f"[CONSERV_AREA] Conservation areas data loaded from API successfully")
        return conservation_areas

    except Exception as err:
        logger.error(
            f"❌ [CONSERV_AREA] Error loading conservation areas: {err}")
        return []


@st.cache_data(ttl=86400)  # Refresh daily
def load_heritage_sites_per_area(radius: int = 5000) -> pd.DataFrame:
    """Load heritage sites once per council area via get_sites, tagging each with its area."""
    records = []
    seen_keys = set()

    for area, (lat, lon) in AREA_CENTERS.items():
        try:
            sites = get_sites(latitude=lat, longitude=lon, radius=radius)
        except Exception as err:
            logger.error(f"Error loading heritage sites for {area}: {err}")
            continue

        for site in sites:
            attrs = site.get("attributes", {})
            point = get_geometry_representative_point(site.get("geometry"))
            # De-duplicate sites that fall within multiple areas' search radii
            dedupe_key = (attrs.get("Name"), point)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            records.append({"area": area, "site_type": "Heritage Site"})

    return pd.DataFrame(records, columns=["area", "site_type"])


@st.cache_data(ttl=86400)  # Refresh daily
def load_conservation_areas_per_area(radius: int = 5000) -> pd.DataFrame:
    """Load conservation areas once per council area via get_conservation_areas, tagging each with its area."""
    records = []
    seen_keys = set()

    for area, (lat, lon) in AREA_CENTERS.items():
        try:
            areas = get_conservation_areas(
                latitude=lat, longitude=lon, radius=radius)
        except Exception as err:
            logger.error(
                f"Error loading conservation areas for {area}: {err}")
            continue

        for site in areas:
            props = site.get("properties", {})
            point = get_geometry_representative_point(site.get("geometry"))
            # De-duplicate areas that fall within multiple areas' search radii
            dedupe_key = (props.get("NAME"), point)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            records.append({"area": area, "site_type": "Conservation Area"})

    return pd.DataFrame(records, columns=["area", "site_type"])


# ==================== DATA FILTERING ====================

def filter_applications(df, selected_areas, selected_types, selected_statuses, date_range, search_query):
    """Apply all filters to the applications DataFrame."""
    filtered_df = df.copy()

    # Filter by area
    if selected_areas:
        filtered_df = filtered_df[filtered_df["area"].isin(
            selected_areas)]

    # Filter by application type
    if selected_types:
        filtered_df = filtered_df[filtered_df["app_type"].isin(selected_types)]

    # Filter by application status
    if selected_statuses:
        filtered_df = filtered_df[filtered_df["app_state"].isin(
            selected_statuses)]

    # Filter by date range
    if date_range[0] and date_range[1]:
        filtered_df = filtered_df[
            (filtered_df["start_date"] >= pd.Timestamp(date_range[0])) &
            (filtered_df["start_date"] <= pd.Timestamp(date_range[1]))
        ]

    # Filter by search query (address or UID)
    if search_query:
        search_lower = search_query.lower()
        filtered_df = filtered_df[
            (filtered_df["address"].astype(str).str.lower().str.contains(search_lower, na=False)) |
            (filtered_df["uid"].astype(str).str.lower(
            ).str.contains(search_lower, na=False))
        ]

    return filtered_df


def filter_applications_by_postcode(df, postcode: str, radius_km: float = 5):
    """
    Filter applications by proximity to a postcode.

    Args:
        df: DataFrame of planning applications
        postcode: UK postcode to search near
        radius_km: Search radius in kilometers (default 5km)

    Returns:
        Tuple of (filtered_df, postcode_coords) where postcode_coords is a dict with 'latitude', 'longitude', 'postcode'
        If postcode is invalid, returns (empty DataFrame, error dict)
    """
    if not postcode or not isinstance(postcode, str):
        return df.copy(), {}

    # Get coordinates from postcode
    postcode_data = get_postcode_coordinates(postcode)

    if 'error' in postcode_data:
        logger.warning(f"Postcode error: {postcode_data['error']}")
        return pd.DataFrame(), postcode_data

    # Extract coordinates
    postcode_lat = postcode_data['latitude']
    postcode_lon = postcode_data['longitude']

    # Filter applications within radius
    radius_meters = radius_km * 1000
    nearby_apps = []

    for idx, row in df.iterrows():
        try:
            if pd.notna(row.get("location_y")) and pd.notna(row.get("location_x")):
                distance = calculate_distance(
                    postcode_lat, postcode_lon,
                    float(row["location_y"]), float(row["location_x"])
                )
                if distance <= radius_meters:
                    nearby_apps.append(idx)
        except (TypeError, ValueError) as err:
            logger.debug(f"Error calculating distance for row: {err}")
            continue

    filtered_df = df.loc[nearby_apps] if nearby_apps else pd.DataFrame()
    logger.info(
        f"Found {len(filtered_df)} applications within {radius_km}km of postcode {postcode}")

    return filtered_df, postcode_data


# ==================== METRICS SECTION ====================

def display_metrics(df):
    """Display area summary metrics at the top of the dashboard."""
    st.subheader("📊 Area Summary")

    # Calculate metrics
    total_apps = len(df)

    areas = df["area"].unique() if not df.empty else []
    area_counts = {area: len(df[df["area"] == area]) for area in areas}

    # Display metrics in columns
    cols = st.columns(len(area_counts) + 1)

    with cols[0]:
        st.metric("Total Applications", total_apps)

    for idx, (area, count) in enumerate(area_counts.items(), 1):
        with cols[idx]:
            st.metric(f"{area}", count)

    st.divider()


# ==================== SIDEBAR FILTERS ====================

def setup_sidebar_filters(df):
    """Setup sidebar filter controls."""
    st.sidebar.header("🔍 Filters")

    # Postcode search (at the top)
    st.sidebar.subheader("📍 Search by Postcode")
    postcode = st.sidebar.text_input(
        "Enter UK postcode",
        placeholder="e.g., E1 6AN",
        help="Search for planning applications near a postcode"
    )

    postcode_radius_m = st.sidebar.slider(
        "Search radius (meters)",
        min_value=50,
        max_value=1000,
        value=500,
        step=50,
        help="How far to search from the postcode (50m-1000m)"
    )

    st.sidebar.divider()

    # Collapsible filters section
    with st.sidebar.expander("🏢 Council Area", expanded=False):
        available_areas = sorted(
            df["area"].unique().tolist()) if not df.empty else []
        selected_areas = st.multiselect(
            "Council Area",
            options=available_areas,
            default=available_areas,
            help="Filter by council area",
            key="areas_filter"
        )

    with st.sidebar.expander("📋 Application Type", expanded=False):
        available_types = sorted(
            df["app_type"].unique().tolist()) if not df.empty else []
        selected_types = st.multiselect(
            "Application Type",
            options=available_types,
            default=available_types,
            help="Filter by planning application type",
            key="types_filter"
        )

    with st.sidebar.expander("✅ Application Status", expanded=False):
        available_statuses = sorted(
            df["app_state"].unique().tolist()) if not df.empty else []
        selected_statuses = st.multiselect(
            "Application Status",
            options=available_statuses,
            default=available_statuses,
            help="Filter by application status",
            key="statuses_filter"
        )

    st.sidebar.divider()

    # Date range filter
    st.sidebar.subheader("📅 Date Range")

    if not df.empty and "start_date" in df.columns:
        min_date = pd.to_datetime(df["start_date"]).min()
        max_date = pd.to_datetime(df["start_date"]).max()
    else:
        min_date = datetime.now() - timedelta(days=365)
        max_date = datetime.now()

    date_range = st.sidebar.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        format="YYYY-MM-DD"
    )

    st.sidebar.divider()

    # Search box
    search_query = st.sidebar.text_input(
        "🔎 Search by address or UID",
        placeholder="e.g., Tower Hamlets or 26/2638",
        help="Type part of an address or application UID"
    )

    st.sidebar.divider()

    # Map layer controls
    st.sidebar.subheader("🗺️ Map Layers")
    show_conservation_areas = st.sidebar.checkbox(
        "Conservation Areas", value=True, help="Show conservation area boundaries")
    show_clustering = st.sidebar.checkbox(
        "Marker Clustering", value=True, help="Group markers at low zoom levels")

    st.sidebar.divider()

    # Refresh button
    if st.sidebar.button("🔄 Refresh Data", help="Force refresh from DynamoDB and API"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.header("📧 Subscribe to Alerts")

    area = st.sidebar.selectbox(
        "Select your area",
        options=["Tower Hamlets", "Newham", "Greenwich"],
        help="Choose which area you want to monitor for planning applications"
    )

    email = st.sidebar.text_input(
        "Enter your email address",
        placeholder="your.email@example.com",
        help="We'll send you alerts about planning applications in your area"
    )

    if st.sidebar.button("Subscribe", use_container_width=True):
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not email or not re.match(email_pattern, email):
            st.sidebar.error("Please enter a valid email address")
        elif not area:
            st.sidebar.error("Please select an area")
        else:
            # Submit to DynamoDB
            result = subscribe_user(area, email)
            if result['success']:
                st.sidebar.success(result['message'])
            else:
                st.sidebar.error(result['message'])

    return {
        "selected_areas": selected_areas,
        "selected_types": selected_types,
        "selected_statuses": selected_statuses,
        "date_range": date_range,
        "search_query": search_query,
        "show_conservation_areas": show_conservation_areas,
        "show_clustering": show_clustering,
        "postcode": postcode,
        "postcode_radius_m": postcode_radius_m,
    }


# ==================== FOLIUM MAP BUILDER ====================

def _conservation_area_style(x):
    """Style function for conservation area polygons (must be module-level for pickling)."""
    return {
        "fillColor": "green",
        "color": "darkgreen",
        "weight": 2,
        "opacity": 0.5,
        "fillOpacity": 0.2,
    }


@st.cache_data(show_spinner=False, ttl=3600)
def build_folium_map(df, heritage_sites, conservation_areas, filters, postcode_coords=None):
    """Build the folium map with all layers and features."""
    import time
    map_start_time = time.time()
    logger.info(f"🗺️ [MAP_BUILD] ===== STARTING MAP BUILD =====")
    logger.info(
        f"[MAP_BUILD] Input data: {len(df)} applications, {len(conservation_areas)} conservation areas")
    logger.info(
        f"[MAP_BUILD] Filters: show_conservation_areas={filters.get('show_conservation_areas')}, show_clustering={filters.get('show_clustering')}")

    if df.empty:
        logger.warning(
            "⚠️ [MAP_BUILD] Empty dataframe - no applications to display")
        st.warning(
            "⚠️ No planning applications to display. Please adjust your filters.")
        return None

    # Determine map center
    zoom_level = 13  # Default zoom
    if 'focused_location' in st.session_state and st.session_state.focused_location:
        center_lat = st.session_state.focused_location['lat']
        center_lon = st.session_state.focused_location['lon']
        zoom_level = st.session_state.focused_location.get('zoom', 16)
        logger.info(
            f"📍 [MAP_BUILD] Map FOCUSED on application {st.session_state.focused_location.get('uid', 'Unknown')} (lat={center_lat:.4f}, lon={center_lon:.4f}, zoom={zoom_level})")
    elif postcode_coords and 'latitude' in postcode_coords and 'longitude' in postcode_coords:
        # Use postcode coordinates as center
        center_lat = postcode_coords['latitude']
        center_lon = postcode_coords['longitude']
        zoom_level = 14
        logger.info(
            f"📍 [MAP_BUILD] Map centered on POSTCODE {postcode_coords.get('postcode', 'Unknown')} (lat={center_lat:.4f}, lon={center_lon:.4f})")
    else:
        # Newham default center
        newham_lat = 51.54
        newham_lon = 0.02

        # Calculate map center based on all applications
        try:
            # Filter out invalid coordinates (NaN or extreme values)
            valid_df = df[
                (df["location_y"].notna()) &
                (df["location_x"].notna()) &
                (df["location_y"].between(51.0, 52.0)) &  # London bounds
                (df["location_x"].between(-0.5, 0.5))     # London bounds
            ]

            if not valid_df.empty:
                center_lat = valid_df["location_y"].mean()
                center_lon = valid_df["location_x"].mean()
                logger.info(
                    f"📍 [MAP_BUILD] Map centered on CALCULATED CENTER from {len(valid_df)} valid applications (lat={center_lat:.4f}, lon={center_lon:.4f})")
            else:
                center_lat = newham_lat
                center_lon = newham_lon
                logger.info(
                    f"📍 [MAP_BUILD] No valid application coordinates, using NEWHAM DEFAULT (lat={center_lat:.4f}, lon={center_lon:.4f})")
        except Exception as err:
            logger.warning(
                f"⚠️ [MAP_BUILD] Error calculating map center: {err}. Defaulting to Newham.")
            center_lat = newham_lat
            center_lon = newham_lon

    # Create base map
    logger.debug(
        f"[MAP_BUILD] Creating base folium map at center (lat={center_lat:.4f}, lon={center_lon:.4f}), zoom={zoom_level}")
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_level,
        tiles="OpenStreetMap"
    )

    # Store heritage sites in session state for popup generation
    st.session_state.heritage_sites = heritage_sites

    # Create a layer for nearby heritage sites
    heritage_sites_layer = folium.FeatureGroup(
        name="Nearby Heritage Sites (within 100m)", show=True).add_to(m)

    # ==================== POSTCODE SEARCH MARKER ====================

    if postcode_coords and 'latitude' in postcode_coords and 'longitude' in postcode_coords:
        postcode_popup = f"""
        <div style="font-family: Arial; font-size: 12px; width: 200px;">
            <b>Postcode Search Center</b><br>
            <b>Postcode:</b> {postcode_coords.get('postcode', 'N/A')}<br>
            <b>Latitude:</b> {postcode_coords.get('latitude', 'N/A'):.6f}<br>
            <b>Longitude:</b> {postcode_coords.get('longitude', 'N/A'):.6f}
        </div>
        """

        folium.Marker(
            location=[postcode_coords['latitude'],
                      postcode_coords['longitude']],
            popup=folium.Popup(postcode_popup, max_width=250),
            tooltip="Postcode Search Center",
            icon=folium.Icon(color="red", icon="location-dot", prefix="fa"),
        ).add_to(m)

    # ==================== PLANNING APPLICATIONS LAYER ====================

    logger.info(
        f"[MAP_BUILD] Starting to add planning applications layer ({len(df)} applications, clustering={filters.get('show_clustering')})")
    app_layer_start_time = time.time()

    # Create boto3 session to read documents
    session = create_boto3_session()

    if filters["show_clustering"]:
        logger.debug(
            f"[MAP_BUILD] Using CLUSTERED marker mode for planning applications")
        # Use marker clustering for dense point data
        marker_cluster = MarkerCluster(
            name="Planning Applications (Clustered)").add_to(m)

        for idx, row in df.iterrows():
            # Load AI summary for the current planning application
            data = dict(row)
            # ai_summary = get_ai_summary(session, data, documents)
            ai_summary = "Not Available"

            app_type = str(row.get("app_type", "Unknown"))
            color = map_app_type_to_folium_color(app_type)

            # Find nearby heritage sites within 100m
            nearby_sites = find_nearby_heritage_sites(
                row["location_y"], row["location_x"], heritage_sites, radius_meters=100
            )

            # Add nearby heritage sites to map layer
            for item in nearby_sites:
                site = item["site"]
                distance = item["distance"]
                attrs = site.get("attributes", {})

                if "geometry" in site and "points" in site["geometry"]:
                    points = site["geometry"]["points"]
                    if points and len(points) > 0:
                        site_lon, site_lat = points[0][0], points[0][1]

                        heritage_popup = f"""
                        <div style="font-family: Arial; font-size: 11px; width: 220px;">
                            <b>{attrs.get('Name', 'Heritage Site')}</b><br>
                            <b>Grade:</b> {attrs.get('Grade', 'N/A')}<br>
                            <b>Distance:</b> {distance:.0f}m<br>
                            <b>From App:</b> {row.get('uid', 'N/A')}<br>
                            <a href="{attrs.get('hyperlink', '#')}" target="_blank">View Details</a>
                        </div>
                        """

                        folium.Marker(
                            location=[site_lat, site_lon],
                            popup=folium.Popup(heritage_popup, max_width=250),
                            tooltip=f"{attrs.get('Name', 'Heritage Site')} ({distance:.0f}m)",
                            icon=folium.Icon(
                                color="blue", icon="star", prefix="fa"),
                        ).add_to(heritage_sites_layer)

            # Build heritage sites section for popup
            heritage_html = ""
            if nearby_sites:
                heritage_html = "<br><b>Nearby Heritage Sites (within 100m):</b><ul style='margin: 5px 0; padding-left: 20px;'>"
                for item in nearby_sites:
                    site = item["site"]
                    distance = item["distance"]
                    attrs = site.get("attributes", {})
                    heritage_html += f"<li>{attrs.get('Name', 'Unknown')} ({distance:.0f}m)<br><small>Grade: {attrs.get('Grade', 'N/A')}</small></li>"
                heritage_html += "</ul>"

            popup_html = f"""
            <div style="font-family: Arial; font-size: 12px; width: 280px;">
                <b>UID:</b> {row.get('uid', 'N/A')}<br>
                <b>Address:</b> {row.get('address', 'N/A')}<br>
                <b>Type:</b> {app_type}<br>
                <b>Status:</b> {row.get('app_state', 'N/A')}<br>
                <b>Area:</b> {row.get('area', 'N/A')}<br>
                <a href="{row.get('url', '#')}" target="_blank">View on Council Website</a>
                {heritage_html}
            </div>
            """

            folium.Marker(
                location=[row["location_y"], row["location_x"]],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{row.get('uid', 'N/A')} - {row.get('address', 'N/A')}",
                icon=folium.Icon(color=color, icon="info-sign"),
            ).add_to(marker_cluster)
    else:
        # Add markers without clustering
        app_layer = folium.FeatureGroup(
            name="Planning Applications", show=True).add_to(m)

        for idx, row in df.iterrows():
            app_type = str(row.get("app_type", "Unknown"))
            color = map_app_type_to_folium_color(app_type)

            # Find nearby heritage sites within 100m
            nearby_sites = find_nearby_heritage_sites(
                row["location_y"], row["location_x"], heritage_sites, radius_meters=100
            )

            # Add nearby heritage sites to map layer
            for item in nearby_sites:
                site = item["site"]
                distance = item["distance"]
                attrs = site.get("attributes", {})

                if "geometry" in site and "points" in site["geometry"]:
                    points = site["geometry"]["points"]
                    if points and len(points) > 0:
                        site_lon, site_lat = points[0][0], points[0][1]

                        heritage_popup = f"""
                        <div style="font-family: Arial; font-size: 11px; width: 220px;">
                            <b>{attrs.get('Name', 'Heritage Site')}</b><br>
                            <b>Grade:</b> {attrs.get('Grade', 'N/A')}<br>
                            <b>Distance:</b> {distance:.0f}m<br>
                            <b>From App:</b> {row.get('uid', 'N/A')}<br>
                            <a href="{attrs.get('hyperlink', '#')}" target="_blank">View Details</a>
                        </div>
                        """

                        folium.Marker(
                            location=[site_lat, site_lon],
                            popup=folium.Popup(heritage_popup, max_width=250),
                            tooltip=f"{attrs.get('Name', 'Heritage Site')} ({distance:.0f}m)",
                            icon=folium.Icon(
                                color="blue", icon="star", prefix="fa"),
                        ).add_to(heritage_sites_layer)

            # Build heritage sites section for popup
            heritage_html = ""
            if nearby_sites:
                heritage_html = "<br><b>Nearby Heritage Sites (within 100m):</b><ul style='margin: 5px 0; padding-left: 20px;'>"
                for item in nearby_sites:
                    site = item["site"]
                    distance = item["distance"]
                    attrs = site.get("attributes", {})
                    heritage_html += f"<li>{attrs.get('Name', 'Unknown')} ({distance:.0f}m)<br><small>Grade: {attrs.get('Grade', 'N/A')}</small></li>"
                heritage_html += "</ul>"

            popup_html = f"""
            <div style="font-family: Arial; font-size: 12px; width: 280px;">
                <b>UID:</b> {row.get('uid', 'N/A')}<br>
                <b>Address:</b> {row.get('address', 'N/A')}<br>
                <b>Type:</b> {app_type}<br>
                <b>Status:</b> {row.get('app_state', 'N/A')}<br>
                <b>Area:</b> {row.get('area', 'N/A')}<br>
                <a href="{row.get('url', '#')}" target="_blank">View on Council Website</a>
                {heritage_html}
            </div>
            """

            folium.Marker(
                location=[row["location_y"], row["location_x"]],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{row.get('uid', 'N/A')} - {row.get('address', 'N/A')}",
                icon=folium.Icon(color=color, icon="info-sign"),
            ).add_to(app_layer)

    # ==================== HERITAGE SITES LAYER ====================
    # Heritage sites are now shown on-demand within planning application popups (within 100m)

    app_layer_elapsed = time.time() - app_layer_start_time
    logger.info(
        f"✅ [MAP_BUILD] Finished adding planning applications layer - Time: {app_layer_elapsed:.3f}s")

    # ==================== CONSERVATION AREAS LAYER ====================

    if filters["show_conservation_areas"] and conservation_areas:
        logger.info(
            f"🟢 [MAP_BUILD] ADDING CONSERVATION AREAS LAYER - {len(conservation_areas)} areas to process")
        conserv_area_start_time = time.time()
        conservation_layer = folium.FeatureGroup(
            name="Conservation Areas", show=True).add_to(m)
        logger.debug(
            f"[MAP_BUILD] Conservation areas FeatureGroup created and added to map")

        conserv_processed = 0
        conserv_skipped = 0
        for idx, area in enumerate(conservation_areas):
            try:
                if "geometry" in area:
                    geometry = area["geometry"]
                    props = area.get("properties", {})
                    area_name = props.get('NAME', 'Conservation Area')

                    popup_text = f"""
                    <div style="font-family: Arial; font-size: 12px;">
                        <b>{area_name}</b>
                    </div>
                    """

                    # Draw polygon
                    folium.GeoJson(
                        {
                            "type": "Feature",
                            "geometry": geometry,
                            "properties": props
                        },
                        style_function=_conservation_area_style,
                        popup=folium.Popup(popup_text, max_width=250),
                        tooltip=area_name,
                    ).add_to(conservation_layer)
                    conserv_processed += 1
                    if conserv_processed % 5 == 0:
                        logger.debug(
                            f"[MAP_BUILD] Processed {conserv_processed} conservation areas so far...")
                else:
                    conserv_skipped += 1
                    logger.debug(
                        f"[MAP_BUILD] Skipping conservation area {idx} - no geometry found")
            except Exception as err:
                conserv_skipped += 1
                logger.debug(
                    f"⚠️ [MAP_BUILD] Error processing conservation area {idx}: {err}")
                continue

        conserv_area_elapsed = time.time() - conserv_area_start_time
        logger.info(
            f"✅ [MAP_BUILD] FINISHED conservation areas layer - Processed: {conserv_processed}, Skipped: {conserv_skipped}, Time: {conserv_area_elapsed:.3f}s")
    else:
        if not filters["show_conservation_areas"]:
            logger.debug(
                f"[MAP_BUILD] Conservation areas layer DISABLED by user filter")
        else:
            logger.debug(
                f"[MAP_BUILD] No conservation areas data available (empty list)")

    # Add layer control
    logger.debug(f"[MAP_BUILD] Adding layer control")
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    map_elapsed = time.time() - map_start_time
    logger.info(
        f"✅ [MAP_BUILD] ===== MAP BUILD COMPLETE - Total time: {map_elapsed:.3f}s =====")

    return m

# ==================== CARD STYLING & STATUS MAPPING ====================


# Dashboard theme colors (from config.toml)
THEME_PRIMARY = "#2e7d32"
THEME_BG = "#0d1f12"
THEME_BG_SECONDARY = "#1b3a20"
THEME_TEXT = "#e6f2e6"
THEME_TEXT_MUTED = "#a3d8a3"

# Map application status to card border color (adapted for dark theme)
STATUS_COLOR_MAP = {
    "Permitted": "#4ade80",      # Bright green for dark theme
    "Undecided": "#fbbf24",      # Amber for dark theme
    "Withdrawn": "#f87171",      # Bright red for dark theme
    "N/A": "#9ca3af",            # Gray
}

# Map application status to badge text
STATUS_BADGE_MAP = {
    "Permitted": "✓ Permitted",
    "Undecided": "⏳ Undecided",
    "Withdrawn": "✗ Withdrawn",
    "N/A": "• No Status",
}

# Map application status to description
STATUS_DESCRIPTION_MAP = {
    "Permitted": "The planning application has been approved by the local authority. The applicant may proceed with the proposed development.",
    "Undecided": "The planning application is currently under review by the local authority. A decision is pending.",
    "Withdrawn": "The applicant has withdrawn their planning application. No decision has been made.",
    "N/A": "The current status of this planning application is not available.",
}

# Map application types to descriptions
APP_TYPE_DESCRIPTION_MAP = {
    "Full": "A full planning permission application for construction, extension, or alteration of buildings and structures.",
    "Outline": "An outline planning permission to establish in principle whether a proposed development is acceptable. Detailed design to follow.",
    "Amendment": "An application to modify or change an existing approved planning permission or conditions.",
    "Conditions": "An application to discharge or vary conditions attached to an existing planning permission.",
    "Trees": "An application related to tree works such as felling, pruning, or planting in a designated conservation area.",
    "Work to Trees": "An application requesting consent for works to protected trees or trees in conservation areas.",
    "Heritage": "An application related to development affecting listed buildings, conservation areas, or other heritage assets.",
    "Listed Building": "An application for works to a listed building requiring Listed Building Consent from the local authority.",
    "Advertising": "An application for the erection or display of advertisements, hoardings, or signage.",
    "Telecoms": "An application related to telecommunications infrastructure, including masts, antennae, or cabinets.",
    "Compliance": "An application to ensure compliance with existing planning conditions or enforcement requirements.",
    "Non-Material Amendment": "An application to make minor changes that are not considered material to an approved planning permission.",
    "N/A": "The application type for this planning application could not be determined.",
    "Other": "A planning application that does not fit into the standard categories listed above.",
}


def get_status_color(status: str) -> str:
    """Get the color for a given application status."""
    return STATUS_COLOR_MAP.get(status, "#9ca3af")


def get_status_badge(status: str) -> str:
    """Get the badge text for a given application status."""
    return STATUS_BADGE_MAP.get(status, "• Unknown")


def get_status_description(status: str) -> str:
    """Get the description for a given application status."""
    return STATUS_DESCRIPTION_MAP.get(status, "Status information not available.")


def get_app_type_description(app_type: str) -> str:
    """Get the description for a given application type."""
    return APP_TYPE_DESCRIPTION_MAP.get(app_type, "Application type information not available.")


def format_date_for_display(date_value) -> str:
    """Format date for display as 'Month DD, YYYY' (e.g., 'Sep 24, 2026')."""
    if pd.isna(date_value) or date_value is None:
        return "N/A"
    try:
        date_obj = pd.to_datetime(date_value)
        return date_obj.strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return "N/A"


def build_summary_card_html(app_info: dict) -> str:
    """Build an HTML card for displaying application details."""
    uid = app_info.get("uid", "N/A")
    address = app_info.get("address", "N/A")
    # Use "type" instead of "app_type" since convert_info_to_dict lowercases keys from popup
    app_type = app_info.get("type", app_info.get("app_type", "N/A"))
    area = app_info.get("area", "N/A")
    # Use "status" instead of "app_state" since convert_info_to_dict lowercases keys from popup
    status = app_info.get("status", app_info.get("app_state", "N/A"))
    start_date = format_date_for_display(app_info.get("start_date", "N/A"))
    summary = app_info.get("summary", "No Summary Available")

    status_color = get_status_color(status)
    status_badge = get_status_badge(status)
    status_desc = get_status_description(status)
    app_type_desc = get_app_type_description(app_type)

    # Escape any HTML characters in text fields
    uid = uid.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    address = address.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    app_type = app_type.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    area = area.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    summary = summary.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    status_desc = status_desc.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    app_type_desc = app_type_desc.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")

    summary_section = f'<div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #2d5a35;"><div style="font-size: 13px; font-weight: 600; color: {THEME_TEXT}; margin-bottom: 8px;">📋 AI Summary</div><div style="font-size: 13px; line-height: 1.5; color: {THEME_TEXT};">{summary}</div></div>'

    # Info icon with tooltip
    status_info_icon = f'<span style="display: inline-block; width: 16px; height: 16px; margin-left: 6px; background-color: {status_color}; color: white; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; font-weight: bold; cursor: help;" title="{status_desc}">?</span>'
    type_info_icon = f'<span style="display: inline-block; width: 16px; height: 16px; margin-left: 6px; background-color: #5a7c5a; color: {THEME_TEXT}; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; font-weight: bold; cursor: help;" title="{app_type_desc}">?</span>'

    card_html = f'<div style="border: 1px solid #2d5a35; border-left: 4px solid {status_color}; border-radius: 8px; padding: 16px; background-color: {THEME_BG_SECONDARY}; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3); font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif;"><div style="margin-bottom: 12px;"><div style="font-size: 16px; font-weight: 700; color: {THEME_TEXT}; word-break: break-word;">{uid}</div><div style="font-size: 12px; font-weight: 500; color: {status_color}; margin-top: 4px;">{status_badge}{status_info_icon}</div></div><div style="height: 1px; background-color: #2d5a35; margin: 12px 0;"></div><div style="margin-bottom: 8px;"><div style="margin-bottom: 10px;"><div style="font-size: 12px; font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">Address</div><div style="font-size: 13px; color: {THEME_TEXT}; word-break: break-word;">{address}</div></div><div style="margin-bottom: 10px;"><div style="font-size: 12px; font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">Date</div><div style="font-size: 13px; color: {THEME_TEXT};">{start_date}</div></div><div style="margin-bottom: 10px;"><div style="font-size: 12px; font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">Type{type_info_icon}</div><div style="font-size: 13px; color: {THEME_TEXT};">{app_type}</div></div><div><div style="font-size: 12px; font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">Council</div><div style="font-size: 13px; color: {THEME_TEXT};">{area}</div></div></div>{summary_section}</div>'

    return card_html


def build_empty_card_html() -> str:
    """Build an empty card with instructions for when no application is selected."""
    return f'<div style="border: 1px solid #2d5a35; border-left: 4px solid {THEME_PRIMARY}; border-radius: 8px; padding: 24px; background-color: {THEME_BG_SECONDARY}; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3); font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; text-align: center;"><div style="font-size: 32px; margin-bottom: 12px;">👆</div><div style="font-size: 14px; font-weight: 500; color: {THEME_TEXT_MUTED};">Click a marker on the map to view application details</div></div>'


# ==================== GET AI SUMMARY OF LATEST CLICKED APPLICATION ====================

def convert_info_to_dict(info_string: str) -> dict:
    """Convert application info string to dictionary, ignoring the last line."""
    lines = info_string.strip().split('\n')

    # Remove the last line (View on Council Website link)
    lines = lines[:-1]

    result = {}
    for line in lines:
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            result[key] = value

    return result


def get_latest_application_summary(map_data: dict, df: pd.DataFrame) -> str:
    latest_app_info = map_data.get(
        "last_object_clicked_popup") if map_data else None

    if latest_app_info and "UID" in latest_app_info:
        latest_app_info = convert_info_to_dict(latest_app_info)
        uid = latest_app_info.get("uid")
        if uid:
            app_data = df[df["uid"] == uid].to_dict(orient="records")[0]
        else:
            app_data = latest_app_info

        # Show placeholder while generating summary
        summary_placeholder = st.empty()
        summary_placeholder.markdown(
            build_empty_card_html(), unsafe_allow_html=True)

        # Generate AI summary
        with st.spinner("Generating summary..."):
            card_html = build_summary_card_html(
                app_data)

        summary_placeholder.markdown(card_html, unsafe_allow_html=True)
    else:
        # Show empty state card
        st.markdown(build_empty_card_html(), unsafe_allow_html=True)


def create_application_card(app: dict) -> str:
    """Build an HTML card for displaying application details."""
    uid = app.get("uid", "N/A")
    address = app.get("address", "N/A")
    # Use "type" instead of "app_type" since convert_info_to_dict lowercases keys from popup
    app_type = app.get("type", app.get("app_type", "N/A"))
    area = app.get("area", "N/A")
    # Use "status" instead of "app_state" since convert_info_to_dict lowercases keys from popup
    status = app.get("status", app.get("app_state", "N/A"))
    start_date = format_date_for_display(app.get("start_date", "N/A"))
    summary = app.get("summary", "No Summary Available")

    status_color = get_status_color(status)
    status_badge = get_status_badge(status)
    status_desc = get_status_description(status)
    app_type_desc = get_app_type_description(app_type)

    # Escape any HTML characters in text fields
    uid = uid.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    address = address.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    app_type = app_type.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    area = area.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    summary = summary.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    status_desc = status_desc.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")
    app_type_desc = app_type_desc.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;")

    card_html = f"""<div style="border: 1px solid #2d5a35; border-left: 4px solid {status_color};
     border-radius: 0px; padding: 16px; background-color: {THEME_BG_SECONDARY};
     box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3); font-family: -apple-system,
     BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 400px;
     display: flex; flex-direction: column;"><div style="margin-bottom: 12px;">
     <div style="font-size: 16px; font-weight: 700; color: {THEME_TEXT}; word-break:
     break-word;">{uid}</div><div style="font-size: 12px; font-weight: 500;
     color: {status_color}; margin-top: 4px;">{status_badge}<span style="display: inline-block; width: 16px; height: 16px; margin-left: 6px; background-color: {status_color}; color: white; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; font-weight: bold; cursor: help;" title="{status_desc}">?</span></div></div><div style="height:
     1px; background-color: #2d5a35; margin: 12px 0;"></div><div style="margin-bottom: 8px;
     flex: 1;"><div style="margin-bottom: 10px;"><div style="font-size: 12px; font-weight:
     500; color: {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">
     Address</div><div style="font-size: 13px; color: {THEME_TEXT}; word-break: break-word;">
     {address}</div></div><div style="margin-bottom: 10px;"><div style="font-size: 12px;
     font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase;
     letter-spacing: 0.5px;">Date</div><div style="font-size: 13px; color: {THEME_TEXT};">
     {start_date}</div></div><div style="margin-bottom: 10px;"><div style="font-size: 12px;
     font-weight: 500; color: {THEME_TEXT_MUTED}; text-transform: uppercase;
     letter-spacing: 0.5px;">Type<span style="display: inline-block; width: 16px; height: 16px; margin-left: 6px; background-color: #5a7c5a; color: {THEME_TEXT}; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; font-weight: bold; cursor: help;" title="{app_type_desc}">?</span></div><div style="font-size: 13px; color: {THEME_TEXT};">
     {app_type}</div></div><div><div style="font-size: 12px; font-weight: 500; color:
     {THEME_TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">Council
     </div><div style="font-size: 13px; color: {THEME_TEXT};">{area}</div></div></div>
     <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #2d5a35;">
     <details style="cursor: pointer;"><summary style="font-size: 12px; font-weight: 600;
     color: {THEME_TEXT}; padding: 4px; user-select: none;">📋 Summary</summary>
     <div style="font-size: 13px; line-height: 1.5; color: {THEME_TEXT}; margin-top: 8px;
     padding: 8px; background-color: #0d1f12; border-radius: 0px;">{summary}</div></details></div></div>"""

    return card_html


def update_session_location(lat, lon, uid=None):
    """Update the session state with the focused location."""
    st.session_state.focused_location = {
        'lat': lat,
        'lon': lon,
        'uid': uid or 'N/A',
        'zoom': 16
    }


def display_filtered_applications(df: pd.DataFrame, original_count: int):
    """Display filtered applications with pagination (10 cards per page)."""
    if not df.empty:
        display_cols = ["uid", "address", "app_type",
                        "app_state", "area", "start_date",
                        "location_y", "location_x", "summary"]
        display_df = df[display_cols].copy()

        # Initialize sort state
        if "sort_order" not in st.session_state:
            st.session_state.sort_order = "Date (Descending - newest first)"

        # Sort control section
        st.subheader("🔀 Sort Options")
        sort_col1, sort_col2 = st.columns([2, 1], gap="medium")
        with sort_col1:
            new_sort = st.selectbox(
                "Sort by:",
                options=[
                    "Date (Descending - newest first)",
                    "Date (Ascending - oldest first)",
                    "UID (A-Z)",
                    "UID (Z-A)"
                ],
                index=[
                    "Date (Descending - newest first)",
                    "Date (Ascending - oldest first)",
                    "UID (A-Z)",
                    "UID (Z-A)"
                ].index(st.session_state.sort_order),
                key="sort_selectbox",
                help="Choose how to sort the list of applications"
            )

            # Update sort order if changed
            if new_sort != st.session_state.sort_order:
                st.session_state.sort_order = new_sort
                st.session_state.current_page = 0  # Reset to first page
                st.rerun()

        # Apply sorting
        try:
            if "Date" in st.session_state.sort_order:
                display_df["start_date"] = pd.to_datetime(
                    display_df["start_date"])
                if "Descending" in st.session_state.sort_order:
                    display_df = display_df.sort_values(
                        "start_date", ascending=False)
                else:
                    display_df = display_df.sort_values(
                        "start_date", ascending=True)
            else:  # Sort by UID
                if "A-Z" in st.session_state.sort_order:
                    display_df = display_df.sort_values("uid", ascending=True)
                else:
                    display_df = display_df.sort_values("uid", ascending=False)
            display_df = display_df.reset_index(drop=True)
        except Exception as e:
            logger.warning(f"Error applying sort: {e}")

        # Pagination setup
        cards_per_page = 9
        total_cards = len(display_df)
        total_pages = (total_cards + cards_per_page - 1) // cards_per_page

        # Initialize pagination state
        if "current_page" not in st.session_state:
            st.session_state.current_page = 0

        st.divider()

        # Pagination buttons (Previous and Next only)
        col1, col2, col3 = st.columns([1, 1, 1], gap="large")
        with col1:
            if st.button("<- Previous Page", disabled=(st.session_state.current_page == 0), use_container_width=True):
                st.session_state.current_page -= 1
                st.rerun()

        with col3:
            if st.button("Next Page ->", disabled=(st.session_state.current_page >= total_pages - 1), use_container_width=True):
                st.session_state.current_page += 1
                st.rerun()

        # Calculate slice indices
        start_id = st.session_state.current_page * cards_per_page
        end_id = start_id + cards_per_page
        page_df = display_df.iloc[start_id:end_id]

        # Summary info
        cards_shown = len(page_df)
        st.info(
            f"✅ Showing {start_id + 1}-{start_id + cards_shown} of {original_count} total applications")

        # Display page number above cards
        st.markdown(
            f"<div style='text-align: center; margin: 16px 0;'><p style='font-size: 14px; font-weight: 600; color: #a3d8a3;'>Page {st.session_state.current_page + 1} of {total_pages}</p></div>", unsafe_allow_html=True)

        # Display cards in 3-column layout
        col = 0
        cols = st.columns(3, gap="medium")
        for row, data in page_df.iterrows():
            with cols[col]:
                card = create_application_card(data)
                st.markdown(card, unsafe_allow_html=True)
                status = data.get("status", data.get("app_state", "N/A"))
                status_color = get_status_color(status)

                st.markdown(f"""
                <style>
                button[key="location_{data.get('uid')}"] {{
                    background: linear-gradient(135deg, {status_color} 0%, {status_color}dd 100%) !important;
                    color: white !important;
                    font-weight: 600 !important;
                    border: 2px solid {status_color} !important;
                    border-radius: 0px !important;
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
                    text-transform: uppercase !important;
                    letter-spacing: 0.5px !important;
                }}
                button[key="location_{data.get('uid')}"]:hover {{
                    background: linear-gradient(135deg, {status_color}dd 0%, {status_color}aa 100%) !important;
                    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.3) !important;
                }}
                button[key="location_{data.get('uid')}"]:active {{
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3), inset 0 1px 2px rgba(0, 0, 0, 0.2) !important;
                }}
                </style>
                """, unsafe_allow_html=True)

                # Jump to Location button with on_click callback
                st.button(
                    "🗺️ Jump to Location",
                    key=f"location_{data.get('uid')}",
                    use_container_width=True,
                    on_click=lambda lat=data.get('location_y'), lon=data.get(
                        'location_x'), uid=data.get('uid', 'N/A'): update_session_location(lat, lon, uid)
                )

                st.space(10)
            col = (col + 1) % 3
    else:
        st.info("No applications to display with current filters.")


# ==================== MAIN APPLICATION ====================

def main():
    """Main application flow."""

    display_title()

    # Load all data
    with st.spinner("⏳ Loading planning applications..."):
        df_all = load_all_applications()

    if df_all.empty:
        st.error(
            "❌ No data available. Please check your AWS configuration and try again.")
        return

    # Setup sidebar filters
    filters = setup_sidebar_filters(df_all)

    # Apply filters
    df_filtered = filter_applications(
        df_all,
        filters["selected_areas"],
        filters["selected_types"],
        filters["selected_statuses"],
        filters["date_range"],
        filters["search_query"]
    )

    # Handle postcode search
    postcode_coords = None
    if filters.get("postcode"):
        with st.spinner(f"🔍 Searching for applications near postcode {filters['postcode']}..."):
            df_postcode_filtered, postcode_coords = filter_applications_by_postcode(
                df_filtered, filters["postcode"], radius_km=filters.get(
                    "postcode_radius_m", 500) / 1000
            )

        if 'error' in postcode_coords:
            st.sidebar.error(f"❌ {postcode_coords['error']}")
            df_filtered = df_filtered  # Keep original filtered data
            postcode_coords = None
        else:
            df_filtered = df_postcode_filtered
            st.sidebar.success(
                f"✅ Postcode {postcode_coords.get('postcode')} found! Showing {len(df_filtered)} nearby applications within {filters.get('postcode_radius_m', 500)}m")

    # Load auxiliary data (shared across tabs)
    with st.spinner("⏳ Loading heritage sites and conservation areas..."):
        logger.info(
            "🔄 [MAIN] Starting to load heritage sites and conservation areas...")
        heritage_sites = load_heritage_sites()
        conservation_areas = load_conservation_areas_data()
        logger.info(
            f"✅ [MAIN] Loaded {len(heritage_sites)} heritage sites and {len(conservation_areas)} conservation areas")

    # Split the dashboard into a map/overview tab and a scratch tab to work in
    tab_overview, tab_workspace = st.tabs(["🗺️ Overview", "🛠️ Insights"])

    with tab_overview:
        # Display metrics
        display_metrics(df_filtered)

        # Build and display map
        st.subheader("📍 Planning Applications Map")

        session = create_boto3_session()
        if df_filtered.empty:
            st.warning(
                "⚠️ No applications match your filters. Try adjusting your selection.")
        else:
            # Create two-column layout: map (70%) + summary (30%)
            col_map, col_summary = st.columns([7, 3], gap="small")

            map_data = None
            with col_map:
                logger.info(
                    f"🎯 [MAIN] Preparing to build map with {len(df_filtered)} filtered applications")
                df_map_filtered = df_filtered.copy()
                try:
                    df_map_filtered = df_map_filtered[(df_map_filtered["location_x"] != 0) & (
                        df_map_filtered["location_y"] != 0)]
                except KeyError:
                    logger.warning(
                        "⚠️ [MAIN] Location columns not found in the data.")
                    st.warning("Location columns not found in the data.")
                df_map_filtered = df_map_filtered[(df_map_filtered["location_x"] != 0) & (
                    df_map_filtered["location_y"] != 0)]
                logger.info(
                    f"🎯 [MAIN] Map will display {len(df_map_filtered)} applications with valid coordinates")
                with st.spinner("🗺️ Building map..."):
                    logger.info(
                        f"🎯 [MAIN] Calling build_folium_map() with conservation_areas={len(conservation_areas)} areas, show_conservation_areas={filters.get('show_conservation_areas')}")
                    m = build_folium_map(df_map_filtered, heritage_sites,
                                         conservation_areas, filters, postcode_coords)

                if m:
                    logger.info(
                        f"🎯 [MAIN] Map build successful, rendering with st_folium()")

                    map_data = st_folium(m, width=None, height=700, returned_objects=[
                        "last_object_clicked_popup"])
                    print(map_data)
                    logger.debug(
                        f"[MAIN] st_folium returned, map_data type: {type(map_data)}")
                else:
                    logger.warning("⚠️ [MAIN] Map build returned None")

            with col_summary:
                # Display summary for the latest clicked application on the map
                get_latest_application_summary(map_data, df_map_filtered)

        # Display results as cards
        st.subheader("📋 Filtered Results")

        display_filtered_applications(df_map_filtered, len(df_all))

    with tab_workspace:
        st.subheader("📊 Visual Insights")
        st.caption(
            "All charts respect the sidebar filters (area, type, status, date range, search, postcode).")

        if df_filtered.empty:
            st.info("No applications to display with current filters.")
        else:
            col_area, col_status = st.columns(2, gap="medium")

            with col_area:
                st.markdown("**Applications per Area**")
                area_chart = build_applications_per_area_chart(df_filtered)
                if area_chart is not None:
                    st.altair_chart(area_chart, use_container_width=True)

            with col_status:
                st.markdown("**Application Status Breakdown**")
                donut_chart = build_status_donut_chart(df_filtered)
                if donut_chart is not None:
                    st.altair_chart(donut_chart, use_container_width=True)

        col_heritage, col_conservation = st.columns(2, gap="medium")

        with col_heritage:
            st.markdown("**Heritage Sites per Area**")
            heritage_chart = build_heritage_bar_chart()
            if heritage_chart is not None:
                st.altair_chart(heritage_chart, use_container_width=True)
            else:
                st.info(
                    "No heritage sites found for the selected area(s).")

        with col_conservation:
            st.markdown("**Conservation Sites per Area**")
            conservation_chart = build_conservation_bar_chart()
            if conservation_chart is not None:
                st.altair_chart(conservation_chart, use_container_width=True)
            else:
                st.info(
                    "No conservation sites found for the selected area(s).")

        col_type, col_status_per_area = st.columns(2, gap="medium")

        with col_type:
            st.markdown("**Application Types per Area**")
            type_chart = build_type_chart_per_area(df_filtered)
            if type_chart is not None:
                st.altair_chart(type_chart, use_container_width=True)
            else:
                st.info(
                    "No application types found for the selected area(s).")


if __name__ == "__main__":
    main()
