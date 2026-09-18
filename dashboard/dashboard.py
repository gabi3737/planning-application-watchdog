"""GeoSpatial Analytical Dashboard for the Planning Application Watchdog."""
from concurrent.interpreters import create
import logging
import math
import streamlit as st
import folium
from streamlit_folium import st_folium
from curl_cffi import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv
import pandas as pd
import boto3

from data_functions import (calculate_distance, get_sites,
                            get_conservation_areas, create_boto3_session,
                            load_application_data, get_coords)

from ai_summary_functions import (load_documents, get_ai_summary)
load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)


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
        if "no data" in area['properties']['NAME'].lower():
            continue
        folium.Polygon(
            locations=[[point[1], point[0]]
                       for point in area["geometry"]["coordinates"][0]],
            popup=f"""Conservation Area: {area['properties']['NAME']}""",
            color="green",
            fill=True,
            fill_color="green",
            dash_array="3, 5",
            weight=1.5,
        ).add_to(m)
    return m


def load_application_html(application: dict):
    return f"""
            <div style="font-family: Arial, sans-serif; width: 280px; padding: 12px;">
                <h3 style="margin: 0 0 12px 0; color: #2c3e50; font-size: 16px; 
                border-bottom: 2px solid #3498db; padding-bottom: 8px;">
                    {application.get('address', 'Unavailable')}
                </h3>
                <div style="margin: 10px 0;">
                    <p style="margin: 6px 0; font-size: 13px;">
                        <b style="color: #34495e;">Application Type:</b> 
                        <span style="color: #555;">{application.get('app_type', 'Unavailable')}</span>
                    </p>
                    <p style="margin: 6px 0; font-size: 13px;">
                        <b style="color: #34495e;">Application Size:</b> 
                        <span style="color: #555;">{application.get('app_size', 'Unavailable')}</span>
                    </p>
                    <p style="margin: 6px 0; font-size: 13px;">
                        <b style="color: #34495e;">UID:</b> 
                        <span style="color: #555; font-family: monospace;">{application.get('uid', 'Unavailable')}</span>
                    </p>
                </div>
            </div>
            """


def add_applications_to_map(m: folium.Map, latitude: float, longitude: float,
                            radius: int, coords_df: pd.DataFrame,
                            applications_df: pd.DataFrame, documents: dict,
                            _session) -> folium.Map:
    """Adds planning applications to the map based on their coordinates."""
    for idx, row in coords_df.iterrows():
        distance = calculate_distance(
            latitude, longitude, row["location_y"], row["location_x"])
        if distance <= radius:
            app = applications_df.iloc[idx].to_dict()
            popup_html = load_application_html(app)
            folium.Marker(
                location=[row["location_y"], row["location_x"]],
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color="green", icon="home")
            ).add_to(m)
    return m


def create_map(latitude: float, longitude: float, radius: int,
               sites: list, areas: list, coords_df: pd.DataFrame,
               applications: pd.DataFrame, documents: dict, session: boto3.Session) -> folium.Map:
    """Creates and populates the Map with planning applications and heritage sites."""
    m = folium.Map(location=[latitude, longitude], zoom_start=18)

    folium.Marker(
        location=[latitude, longitude],
        popup=f"Center: ({latitude}, {longitude})",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)

    m = add_sites_to_map(m, sites)
    m = add_areas_to_map(m, areas)
    m = add_applications_to_map(m, latitude, longitude, radius, coords_df,
                                applications, documents, session)
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

    use_map_click = st.sidebar.checkbox(
        "Use click to set location",
        value=False,
        help="When enabled, clicking on the map will set latitude and longitude",
    )

    latitude = st.sidebar.number_input(
        "Latitude",
        value=51.54,
        step=0.0001,
        format="%.5f",
        disabled=use_map_click,
    )
    longitude = st.sidebar.number_input(
        "Longitude",
        value=0.05,
        step=0.0001,
        format="%.5f",
        disabled=use_map_click,
    )
    radius = st.sidebar.number_input("Radius (m)", value=100, min_value=0)

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


@st.cache_data
def load_map_data(lat: float, lon: float, radius: int, _session: boto3.Session) -> tuple[list, list, pd.DataFrame]:
    """Fetches heritage sites, conservation areas, and planning application."""
    sites = get_sites(lat, lon, radius)
    areas = get_conservation_areas(lat, lon, radius)
    applications = load_application_data(_session)
    return sites, areas, applications


def update_click_selection(use_map_click: bool, map_data: dict) -> None:
    """Updates the session state location when the map is clicked."""
    if use_map_click and map_data and "last_clicked" in map_data and map_data["last_clicked"]:
        clicked = map_data["last_clicked"]
        st.session_state.selected_lat = clicked["lat"]
        st.session_state.selected_lon = clicked["lng"]


def display_summary_selection(applications: pd.DataFrame, session: boto3.Session, documents: dict) -> None:
    st.divider()
    st.header("📋 Application Summary")

    col1, col2 = st.columns([3, 1], gap="small")
    with col1:
        selected_uid = st.text_input(
            "Enter Application UID to get summary:",
            value=st.session_state.get('selected_uid', ''),
            key='uid_input'
        )
    with col2:
        st.write("")
        get_summary_btn = st.button("Get Summary", use_container_width=True)

    if get_summary_btn:
        if selected_uid:
            matching_app = applications[applications['uid'] == selected_uid]
            if not matching_app.empty:
                app = matching_app.iloc[0].to_dict()
                with st.spinner("Generating summary..."):
                    summary = get_ai_summary(session, app, documents)
                    st.markdown(
                        f"<div style='background-color: #27ae60; padding: 15px; border-radius: 5px; color: white;'>"
                        f"✅ <b>Summary:</b> {summary}"
                        f"</div>",
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    f"<div style='background-color: #c0392b; padding: 15px; border-radius: 5px; color: white;'>"
                    f"❌ <b>Application UID not found</b>"
                    f"</div>",
                    unsafe_allow_html=True
                )
        else:
            st.markdown(
                f"<div style='background-color: #c0392b; padding: 15px; border-radius: 5px; color: white;'>"
                f"❌ <b>Please enter a UID</b>"
                f"</div>",
                unsafe_allow_html=True
            )


def main() -> None:
    """Runs the Planning Application Watchdog dashboard."""
    render_page()

    use_map_click, latitude, longitude, radius = render_sidebar_controls()
    lat, lon = resolve_selected_location(
        use_map_click, latitude, longitude)

    st.write(f"Selected Location: ({lat:.5f}, {lon:.5f})")

    session = create_boto3_session()
    documents = load_documents(session)

    sites, areas, applications = load_map_data(lat, lon, radius, session)
    coords = get_coords(applications)

    m = create_map(lat, lon, radius, sites, areas,
                   coords, applications, documents, session)
    map_data = st_folium(m, width=900, height=600, key="analysis_map")

    update_click_selection(use_map_click, map_data)

    display_summary_selection(applications, session, documents)


if __name__ == "__main__":
    main()
