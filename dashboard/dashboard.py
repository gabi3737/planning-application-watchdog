import streamlit as st
import folium
from streamlit_folium import st_folium
from curl_cffi import requests
import time
import math

fake_applications = [{
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


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the distance in meters between two coordinates using the Haversine formula."""
    R = 6371000  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    diff_phi = math.radians(lat2 - lat1)
    diff_long = math.radians(lon2 - lon1)

    a = math.sin(diff_phi/2)**2 + math.cos(phi1) * \
        math.cos(phi2) * math.sin(diff_long/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def add_applications_to_map(m: folium.Map, latitude: float, longitude: float, radius: int, fake_applications: list) -> None:
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
    for site in sites:
        folium.Marker(
            location=[site["geometry"]["points"]
                      [0][1], site["geometry"]["points"][0][0]],
            popup=f"Heritage Site {site['attributes']['Name']}: Grade {site['attributes']['Grade']}, Link: {site['attributes']['hyperlink']}",
            icon=folium.Icon(color="blue", icon="tower")
        ).add_to(m)
    return m


def create_map(latitude: float, longitude: float, radius: int,
               fake_applications: list, sites: list) -> folium.Map:
    """Creates and populates the Map with planning applications and heritage sites."""
    m = folium.Map(location=[latitude, longitude], zoom_start=10)

    folium.Marker(
        location=[latitude, longitude],
        popup=f"Center: ({latitude}, {longitude})",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)

    m = add_applications_to_map(
        m, latitude, longitude, radius, fake_applications)

    m = add_sites_to_map(m, sites)

    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=False,
        fill_opacity=0.1
    ).add_to(m)

    return m


@st.cache_data
def get_sites(latitude: float, longitude: float, radius: int) -> list:
    """Fetches heritage sites within the specified radius of the given latitude and longitude."""
    url = f"https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/0/query?f=json&geometry={longitude},{latitude}&geometryType=esriGeometryPoint&where=1%3D1&outSR=4326&inSR=4326&distance={radius}&outFields=Name,Grade,Hyperlink&returnGeometry=true"
    heritage_sites_data = requests.get(impersonate="chrome124", url=url).json()
    return heritage_sites_data["features"]


def select_parameters() -> tuple[float, float, int]:
    """Displays sidebar inputs for latitude, longitude, and radius, and returns the selected values."""
    latitude = st.sidebar.number_input(
        "Latitude", value=51.5074, step=0.0001, format="%.5f")
    longitude = st.sidebar.number_input(
        "Longitude", value=-0.1278, step=0.0001, format="%.5f")
    radius = st.sidebar.number_input("Radius (m)", value=100)
    return latitude, longitude, radius


if __name__ == "__main__":
    st.title("Planning Application Watchdog")
    st.set_page_config(
        page_title="Planning Application Watchdog",
        page_icon=":house:",
        layout="wide",
    )

    # Add some introductory text
    st.write("Welcome to the Planning Application Watchdog. Use the map below to explore planning applications in your area.")
    st.write("You can zoom in and out of the map and click on markers to get more information about each planning application.")
    st.write("Use the filters on the sidebar to narrow down the planning applications displayed on the map.")
    st.write(
        "Click on the markers to view detailed information about each location.")

    # Input latitude and longitude for the map center
    latitude, longitude, radius = select_parameters()

    sites = get_sites(latitude, longitude, radius)

    m = create_map(latitude, longitude, radius, fake_applications, sites)

    # Display the map in Streamlit
    map_data = st_folium(m, width=700, height=500)
