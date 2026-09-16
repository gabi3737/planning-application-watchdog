"""GeoSpatial Analytical Dashboard for the Planning Application Watchdog."""
import logging
import math
import streamlit as st
import folium
from streamlit_folium import st_folium
from curl_cffi import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv

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


@st.cache_data
def get_sites(latitude: float, longitude: float, radius: int) -> list:
    """Fetches heritage sites within the specified radius of the given latitude and longitude."""
    base_url = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/0/"
    query = f"query?f=json&geometry={longitude},{latitude}&geometryType=esriGeometryPoint&where=1%3D1&outSR=4326&inSR=4326&distance={radius}&outFields=Name,Grade,Hyperlink&returnGeometry=true"
    url = base_url + query
    try:
        heritage_sites_data = requests.get(
            impersonate="chrome124", url=url).json()
    except HTTPError as err:
        logger.error(f"HTTP Error fetching heritage sites: {err}")
        return []
    if "features" not in heritage_sites_data:
        logger.error("Invalid data format received for heritage sites.")
        return []
    if len(heritage_sites_data["features"]) == 0:
        logger.info("No heritage sites found within the specified radius")
        return []
    return heritage_sites_data["features"]


@st.cache_data
def get_conservation_areas(latitude: float, longitude: float, radius: int) -> list:
    """Fetches conservation areas within the specified radius of the given latitude and longitude."""
    base_url = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/Conservation_Areas/FeatureServer/0/"
    query = f"query?f=geojson&geometry={longitude},{latitude}&geometryType=esriGeometryPoint&inSR=4326&outSR=4326&distance={radius}&where=1%3D1&outFields=NAME&returnGeometry=true"
    url = base_url + query
    try:
        conservation_areas_data = requests.get(
            impersonate="chrome124", url=url).json()
    except HTTPError as err:
        logger.error(f"HTTP Error fetching conservation areas: {err}")
        return []
    if "features" not in conservation_areas_data:
        logger.error("Invalid data format received for conservation areas.")
        return []
    if len(conservation_areas_data["features"]) == 0:
        logger.info("No conservation areas found within the specified radius")
        return []
    return conservation_areas_data["features"]


def select_parameters() -> tuple[float, float, int]:
    """Displays sidebar inputs for latitude, longitude, and radius."""
    st.sidebar.header("📊 Visualization Controls")
    latitude = st.sidebar.number_input(
        "Latitude", value=51.54, step=0.0001, format="%.5f")
    longitude = st.sidebar.number_input(
        "Longitude", value=0.05, step=0.0001, format="%.5f")
    radius = st.sidebar.number_input("Radius (m)", value=100)
    return latitude, longitude, radius


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
            icon=folium.Icon(color="purple", icon="tree"),
            color="green",
            fill=True,
            fill_color="green"
        ).add_to(m)
    return m


def create_map(latitude: float, longitude: float, radius: int,
               fake_applications: list, sites: list, areas: list) -> folium.Map:
    """Creates and populates the Map with planning applications and heritage sites."""
    m = folium.Map(location=[latitude, longitude], zoom_start=12)

    folium.Marker(
        location=[latitude, longitude],
        popup=f"Center: ({latitude}, {longitude})",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)

    m = add_applications_to_map(
        m, latitude, longitude, radius, fake_applications)

    m = add_sites_to_map(m, sites)
    areas = get_conservation_areas(latitude, longitude, radius)
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
        page_icon=":house:",
        layout="wide",
    )

    st.write("Welcome to the Planning Application Watchdog. "
             "Use the map below to explore planning applications in your area.")
    st.write("You can zoom in and out of the map and click on markers to get more information"
             " about each planning application.")
    st.write("Use the filters on the sidebar to narrow down the planning applications "
             "displayed on the map.")
    st.write(
        "Click on the markers to view detailed information about each location.")

    lat, lon, r = select_parameters()

    sites = get_sites(lat, lon, r)
    areas = get_conservation_areas(lat, lon, r)

    m = create_map(lat, lon, r, FAKE_APPLICATIONS, sites, areas)

    # Display the map in Streamlit
    map_data = st_folium(m, width=700, height=500)
