"""
Enhanced Planning Application Watchdog Dashboard v2
Features:
- Loads all planning applications from 3 council areas at startup (no radius dependency)
- Displays area-summary metrics at the top
- Interactive folium map with marker clustering, toggleable layers, and search/filtering
- Sidebar controls for filtering by area, type, status, date range, and address/UID search
"""

import streamlit as st
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import pandas as pd
import logging
import re
import boto3
from datetime import datetime, timedelta
from data_functions import (
    load_application_data,
    get_sites,
    get_conservation_areas,
    APP_TYPE_COLORS,
    create_boto3_session,
    calculate_distance,
)
from ai_summary_functions import load_documents, convert_info_to_dict, get_ai_summary
from dynamodb_functions import subscribe_user

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

# ==================== STREAMLIT PAGE CONFIG ====================
st.set_page_config(
    page_title="Planning Application Watchdog v2",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🗺️ Planning Application Watchdog v2")

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
        # Use same regional center as heritage sites
        conservation_areas = get_conservation_areas(
            latitude=51.51, longitude=-0.01, radius=20000)
        logger.info(f"Loaded {len(conservation_areas)} conservation areas")
        return conservation_areas

    except Exception as err:
        logger.error(f"Error loading conservation areas: {err}")
        return []


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

    # Area filter
    available_areas = sorted(
        df["area"].unique().tolist()) if not df.empty else []
    selected_areas = st.sidebar.multiselect(
        "Council Area",
        options=available_areas,
        default=available_areas,
        help="Filter by council area"
    )

    # Application type filter
    available_types = sorted(
        df["app_type"].unique().tolist()) if not df.empty else []
    selected_types = st.sidebar.multiselect(
        "Application Type",
        options=available_types,
        default=available_types,
        help="Filter by planning application type"
    )

    # Application status filter
    available_statuses = sorted(
        df["app_state"].unique().tolist()) if not df.empty else []
    selected_statuses = st.sidebar.multiselect(
        "Application Status",
        options=available_statuses,
        default=available_statuses,
        help="Filter by application status"
    )

    st.sidebar.divider()

    # Date range filter
    st.sidebar.subheader("Date Range")

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
    }


# ==================== FOLIUM MAP BUILDER ====================

def build_folium_map(df, heritage_sites, conservation_areas, filters, documents):
    """Build the folium map with all layers and features."""

    if df.empty:
        st.warning(
            "⚠️ No planning applications to display. Please adjust your filters.")
        return None

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
        else:
            center_lat = newham_lat
            center_lon = newham_lon
    except Exception as err:
        logger.warning(
            f"Error calculating map center: {err}. Defaulting to Newham.")
        center_lat = newham_lat
        center_lon = newham_lon

    # Create base map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="OpenStreetMap"
    )

    # Store heritage sites in session state for popup generation
    st.session_state.heritage_sites = heritage_sites

    # Create a layer for nearby heritage sites
    heritage_sites_layer = folium.FeatureGroup(
        name="Nearby Heritage Sites (within 100m)", show=True).add_to(m)

    # ==================== PLANNING APPLICATIONS LAYER ====================

    # Create boto3 session to read documents
    session = create_boto3_session()

    if filters["show_clustering"]:
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

    # ==================== CONSERVATION AREAS LAYER ====================

    if filters["show_conservation_areas"] and conservation_areas:
        conservation_layer = folium.FeatureGroup(
            name="Conservation Areas", show=True).add_to(m)

        for area in conservation_areas:
            try:
                if "geometry" in area:
                    geometry = area["geometry"]
                    props = area.get("properties", {})

                    popup_text = f"""
                    <div style="font-family: Arial; font-size: 12px;">
                        <b>{props.get('NAME', 'Conservation Area')}</b>
                    </div>
                    """

                    # Draw polygon
                    folium.GeoJson(
                        {
                            "type": "Feature",
                            "geometry": geometry,
                            "properties": props
                        },
                        style_function=lambda x: {
                            "fillColor": "green",
                            "color": "darkgreen",
                            "weight": 2,
                            "opacity": 0.5,
                            "fillOpacity": 0.2,
                        },
                        popup=folium.Popup(popup_text, max_width=250),
                        tooltip=props.get('NAME', 'Conservation Area'),
                    ).add_to(conservation_layer)
            except Exception as err:
                logger.debug(f"Error processing conservation area: {err}")
                continue

    # Add layer control
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    return m

# ==================== GET AI SUMMARY OF LATEST CLICKED APPLICATION ====================


def get_latest_application_summary(session: boto3.Session, map_data: dict, documents: dict) -> str:
    st.subheader("Summary")
    latest_app_info = map_data.get(
        "last_object_clicked_popup") if map_data else None

    if latest_app_info:
        latest_app_info = convert_info_to_dict(latest_app_info)

    if latest_app_info:
        st.success(f"Application UID: **{latest_app_info['uid']}**")
        with st.spinner("Generating summary..."):
            summary = get_ai_summary(session, latest_app_info, documents)
            st.info(summary)
    else:
        st.warning("No application selected.")


# ==================== MAIN APPLICATION ====================

def main():
    """Main application flow."""

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

    # Display metrics
    display_metrics(df_filtered)

    # Load auxiliary data
    with st.spinner("⏳ Loading heritage sites and conservation areas..."):
        heritage_sites = load_heritage_sites()
        conservation_areas = load_conservation_areas_data()

    # Build and display map
    st.subheader("📍 Planning Applications Map")

    session = create_boto3_session()
    documents = load_documents(session)
    if df_filtered.empty:
        st.warning(
            "⚠️ No applications match your filters. Try adjusting your selection.")
    else:
        with st.spinner("🗺️ Building map..."):
            m = build_folium_map(df_filtered, heritage_sites,
                                 conservation_areas, filters, documents)

        if m:
            map_data = st_folium(m, width=1400, height=700, returned_objects=[
                "last_object_clicked_popup"])

    # Display summary for the latest clicked application on the map
    get_latest_application_summary(session, map_data, documents)

    # Display results table
    st.subheader("📋 Filtered Results")

    if not df_filtered.empty:
        display_cols = ["uid", "address", "app_type",
                        "app_state", "area", "start_date"]
        display_df = df_filtered[display_cols].copy()
        display_df = display_df.rename(columns={
            "uid": "UID",
            "address": "Address",
            "app_type": "Type",
            "app_state": "Status",
            "area": "Area",
            "start_date": "Date Received"
        })

        st.dataframe(display_df, width="stretch", hide_index=True)
        st.info(
            f"✅ Showing {len(df_filtered)} of {len(df_all)} total applications")
    else:
        st.info("No applications to display with current filters.")


if __name__ == "__main__":
    main()
