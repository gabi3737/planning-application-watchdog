"""GeoSpatial Analytical Dashboard for the Planning Application Watchdog."""
import logging
import math
import streamlit as st
import folium
from streamlit_folium import st_folium
from curl_cffi import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv

from data_functions import calculate_distance, get_sites, get_conservation_areas

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)

FAKE_APPLICATIONS = [{
    "name": "1",
    "latitude": 51.509,
    "longitude": -0.128
},
    {
    "name": "2",
    "latitude": 51.507,
    "longitude": -0.128
},
    {
    "name": "3",
    "latitude": 51.507,
    "longitude": -0.125
}]


# def select_parameters() -> tuple[float, float, int]:
#     """Displays sidebar inputs for latitude, longitude, and radius."""
#     st.sidebar.header("📊 Visualization Controls")
#     latitude = st.sidebar.number_input(
#         "Latitude", value=51.54, step=0.0001, format="%.5f")
#     longitude = st.sidebar.number_input(
#         "Longitude", value=0.05, step=0.0001, format="%.5f")
#     radius = st.sidebar.number_input("Radius (m)", value=100)
#     return latitude, longitude, radius


def add_applications_to_map(m: folium.Map, latitude: float, longitude: float,
                            radius: int, fake_applications: list) -> None:
    for app in fake_applications:
        distance = calculate_distance(
            latitude, longitude, app["latitude"], app["longitude"])
        if distance <= radius:
            folium.Marker(
                location=[app["latitude"], app["longitude"]],
                popup=f"Application {app['name']}: ({app['latitude']}, {app['longitude']})",
                icon=folium.Icon(color="green", icon="home")
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


def create_map(latitude: float, longitude: float, radius: int,
               fake_applications: list, sites: list, areas: list) -> folium.Map:
    """Creates and populates the Map with planning applications and heritage sites."""
    m = folium.Map(location=[latitude, longitude], zoom_start=18)

    folium.Marker(
        location=[latitude, longitude],
        popup=f"Center: ({latitude}, {longitude})",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)

    m = add_applications_to_map(
        m, latitude, longitude, radius, fake_applications)

    m = add_sites_to_map(m, sites)
    m = add_areas_to_map(m, areas)

    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=False,
        fill_opacity=0.1
    ).add_to(m)

    return m


if __name__ == "__main__":
    st.title("Planning Application Watchdog")
    st.set_page_config(
        page_title="Planning Application Watchdog",
        page_icon="🏠",
        layout="wide",
    )

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

    # Sidebar controls
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

    if "selected_lat" not in st.session_state:
        st.session_state.selected_lat = latitude
    if "selected_lon" not in st.session_state:
        st.session_state.selected_lon = longitude

    if use_map_click:
        lat = st.session_state.selected_lat
        lon = st.session_state.selected_lon
    else:
        lat = latitude
        lon = longitude

    st.write(f"Selected Location: ({lat:.5f}, {lon:.5f})")

    sites = get_sites(lat, lon, radius)
    areas = get_conservation_areas(lat, lon, radius)

    m = create_map(lat, lon, radius, FAKE_APPLICATIONS, sites, areas)

    map_data = st_folium(m, width=900, height=600, key="analysis_map")

    if use_map_click and map_data and "last_clicked" in map_data and map_data["last_clicked"]:
        clicked = map_data["last_clicked"]
        st.session_state.selected_lat = clicked["lat"]
        st.session_state.selected_lon = clicked["lng"]
