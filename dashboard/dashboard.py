"""GeoSpatial Analytical Dashboard for the Planning Application Watchdog."""
import logging
import math
import streamlit as st
import folium
from streamlit_folium import st_folium
from curl_cffi import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv
import pandas as pd


from data_functions import (calculate_distance, get_sites, get_conservation_areas,
                            get_planning_applications_by_area, APP_TYPE_COLORS, create_boto3_session)
from dynamodb_functions import subscribe_user
import re
from data_functions import (calculate_distance, get_sites,
                            get_conservation_areas, create_boto3_session,
                            load_application_data, get_coords)

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)


# def select_parameters() -> tuple[float, float, int]:
#     """Displays sidebar inputs for latitude, longitude, and radius."""
#     st.sidebar.header("📊 Visualization Controls")
#     latitude = st.sidebar.number_input(
#         "Latitude", value=51.54, step=0.0001, format="%.5f")
#     longitude = st.sidebar.number_input(
#         "Longitude", value=0.05, step=0.0001, format="%.5f")
#     radius = st.sidebar.number_input("Radius (m)", value=100)
#     return latitude, longitude, radius


def add_applications_to_map(m: folium.Map, applications: list) -> folium.Map:
    """Adds planning applications to the map with color-coded markers by application type."""
    for app in applications:
        # Determine marker color based on application type
        app_type = app.get("app_type", "Unknown")
        color = APP_TYPE_COLORS.get(app_type, "gray")

        # Build popup content with application details
        uid = app.get("uid", "N/A")
        address = app.get("address", "N/A")
        app_state = app.get("app_state", "N/A")
        url = app.get("url", "#")

        popup_text = f"""
        <b>Application: {uid}</b><br>
        <b>Address:</b> {address}<br>
        <b>Type:</b> {app_type}<br>
        <b>Status:</b> {app_state}<br>
        <a href="{url}" target="_blank">View on Council Website</a>
        """

        folium.Marker(
            location=[app["location_y"], app["location_x"]],
            popup=folium.Popup(popup_text, max_width=300),
            icon=folium.Icon(color=color, icon="file", prefix="fa"),
            tooltip=f"{uid} - {address}"
        ).add_to(m)

    return m


def add_sites_to_map(m: folium.Map, sites: list) -> folium.Map:
    """Adds heritage sites to the map."""
    for site in sites:
        folium.Marker(
            location=[site["geometry"]["points"]
                      [0][1], site["geometry"]["points"][0][0]],
            popup=f"""Heritage Site: {site['attributes']['Name']}, 
            Grade: {site['attributes']['Grade']}, 
            Link: {site['attributes']['hyperlink']}""",
            icon=folium.Icon(color="blue", icon="tower")
        ).add_to(m)
    return m


def add_areas_to_map(m: folium.Map, areas: list) -> folium.Map:
    """Adds conservation areas to the map."""
    for area in areas:
        folium.Polygon(
            locations=[[point[1], point[0]]
                       for point in area["geometry"]["coordinates"][0]],
            popup=f"""Conservation Area: {area['properties']['NAME']}""",
            color="green",
            fill=True,
            fill_color="green"
        ).add_to(m)
    return m


def add_applications_to_map(m: folium.Map, latitude: float, longitude: float,
                            radius: int, coords_df: pd.DataFrame) -> folium.Map:
    """Adds planning applications to the map based on their coordinates."""
    for _, row in coords_df.iterrows():
        distance = calculate_distance(
            latitude, longitude, row["location_y"], row["location_x"])
        if distance <= radius:
            folium.Marker(
                location=[row["location_y"], row["location_x"]],
                popup=f"Application: ({row['location_y']}, {row['location_x']})",
                icon=folium.Icon(color="green", icon="home")
            ).add_to(m)
    return m


def create_map(latitude: float, longitude: float, radius: int,
               sites: list, areas: list, coords_df: pd.DataFrame) -> folium.Map:
    """Creates and populates the Map with planning applications and heritage sites."""
    m = folium.Map(location=[latitude, longitude], zoom_start=18)

    folium.Marker(
        location=[latitude, longitude],
        popup=f"Center: ({latitude}, {longitude})",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)

    m = add_applications_to_map(m, applications)

    m = add_sites_to_map(m, sites)
    m = add_areas_to_map(m, areas)
    m = add_applications_to_map(m, latitude, longitude, radius, coords_df)

    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=False,
        fill_opacity=0.1
    ).add_to(m)

    return m


def render_page() -> None:
    """Renders the page title, config, and introductory text."""
    st.set_page_config(
        page_title="Planning Application Watchdog",
        page_icon="🏠",
        layout="wide",
    )

    logo_col, title_col = st.columns([1, 6], vertical_alignment="center")
    with logo_col:
        st.markdown(
            """
            <style>
            [data-testid="stImage"] img {
                image-rendering: -webkit-optimize-contrast;
                image-rendering: high-quality;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.image("./assets/planwatch.png", width=240)
    with title_col:
        st.title("Planning Application Watchdog")

    st.write(
        "Welcome to the Planning Application Watchdog. "
        "Use the map below to explore planning applications in your area."
    )
    st.write(
        "You can zoom in and out of the map and click on markers to get more information "
        "about each planning application."
    )
    st.write(
        "Use the filters on the sidebar to narrow down the planning applications "
        "displayed on the map."
    )
    st.write(
        "Click on the markers to view detailed information about each location."
    )


def render_sidebar_controls() -> tuple[bool, float, float, int]:
    """Displays sidebar inputs and returns use_map_click, latitude, longitude, and radius."""
    st.sidebar.header("📊 Visualization Controls")

    # Initialize map center in session state if needed
    if "map_center_lat" not in st.session_state:
        st.session_state.map_center_lat = 51.54
    if "map_center_lon" not in st.session_state:
        st.session_state.map_center_lon = -0.05

    # Display current map center
    st.sidebar.metric("Map Center Latitude",
                      f"{st.session_state.map_center_lat:.5f}", delta=None)
    st.sidebar.metric("Map Center Longitude",
                      f"{st.session_state.map_center_lon:.5f}", delta=None)

    radius = st.sidebar.number_input(
        "Search Radius (m)", value=100, min_value=0)

    # Planning applications filter
    st.sidebar.divider()
    filter_by_area = st.sidebar.checkbox(
        "Filter planning applications by area",
        value=False,
        help="When enabled, only shows applications from your selected area"
    )

    # Subscriber form section
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

    return use_map_click, latitude, longitude, radius


def resolve_selected_location(use_map_click: bool, latitude: float,
                              longitude: float) -> tuple[float, float]:
    """Resolves the active latitude/longitude from sidebar inputs or map clicks."""
    if "selected_lat" not in st.session_state:
        st.session_state.selected_lat = latitude
    if "selected_lon" not in st.session_state:
        st.session_state.selected_lon = longitude

    if use_map_click:
        return st.session_state.selected_lat, st.session_state.selected_lon
    return latitude, longitude


def load_map_data(lat: float, lon: float, radius: int) -> tuple[list, list, pd.DataFrame]:
    """Fetches heritage sites, conservation areas, and planning application coordinates."""
    sites = get_sites(lat, lon, radius)
    areas = get_conservation_areas(lat, lon, radius)
    coords = get_coords(load_application_data(create_boto3_session()))
    return sites, areas, coords


def update_click_selection(use_map_click: bool, map_data: dict) -> None:
    """Updates the session state location when the map is clicked."""
    if use_map_click and map_data and "last_clicked" in map_data and map_data["last_clicked"]:
        clicked = map_data["last_clicked"]
        st.session_state.selected_lat = clicked["lat"]
        st.session_state.selected_lon = clicked["lng"]


def main() -> None:
    """Runs the Planning Application Watchdog dashboard."""
    render_page()

    use_map_click, latitude, longitude, radius = render_sidebar_controls()
    lat, lon = resolve_selected_location(
        use_map_click, latitude, longitude)

    st.write(f"Selected Location: ({lat:.5f}, {lon:.5f})")

    sites, areas, coords = load_map_data(lat, lon, radius)

    m = create_map(lat, lon, radius, sites, areas, coords)
    map_data = st_folium(m, width=900, height=600, key="analysis_map")

    update_click_selection(use_map_click, map_data)


if __name__ == "__main__":
    main()
