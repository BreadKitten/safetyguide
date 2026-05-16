'use client';

import {
  MapContainer,
  TileLayer,
  CircleMarker,
  GeoJSON,
  Popup,
} from 'react-leaflet';
import { useEffect, useState } from 'react';

import 'leaflet/dist/leaflet.css';

export default function Map() {
  const [police, setPolice] = useState(null);
  const [fire, setFire] = useState(null);
  const [hospital, setHospital] = useState(null);
  const [counties, setCounties] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch('/policestation.geojson').then((r) => r.json()),
      fetch('/firestation.geojson').then((r) => r.json()),
      fetch('/hospital.geojson').then((r) => r.json()),
      fetch('/wa_counties.geojson').then((r) => r.json()),
    ]).then(([p, f, h, c]) => {
      setPolice(p);
      setFire(f);
      setHospital(h);
      setCounties(c);
    });
  }, []);

  const center = [47.5, -120.5];

  return (
    <div className='w-full h-screen'>
      <MapContainer
        center={center}
        zoom={7}
        scrollWheelZoom={true}
        className='w-full h-full'
      >
        {/* SATELLITE TILE LAYER */}
        <TileLayer
          url='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
          attribution='Tiles © Esri'
        />

        {/* COUNTY BORDERS */}
        {counties && (
          <GeoJSON
            data={counties}
            style={{
              color: '#374151',
              weight: 1,
              fillOpacity: 0,
            }}
          />
        )}

        {/* FIRE STATIONS (RED) */}
        {fire &&
          fire.features.map((f) => {
            const [lng, lat] = f.geometry.coordinates;

            return (
              <CircleMarker
                key={f.properties.OBJECTID}
                center={[lat, lng]}
                radius={5}
                pathOptions={{
                  color: 'white',
                  weight: 1,
                  fillColor: '#dc2626',
                  fillOpacity: 1,
                }}
              >
                <Popup>
                  <strong>Fire Station</strong>
                  <br />
                  {f.properties.NAME}
                  <br />
                  {f.properties.ADDRESS}
                </Popup>
              </CircleMarker>
            );
          })}

        {/* POLICE STATIONS (BLUE) */}
        {police &&
          police.features.map((p) => {
            const [lng, lat] = p.geometry.coordinates;

            return (
              <CircleMarker
                key={p.properties.OBJECTID}
                center={[lat, lng]}
                radius={5}
                pathOptions={{
                  color: 'white',
                  weight: 1,
                  fillColor: '#2563eb',
                  fillOpacity: 1,
                }}
              >
                <Popup>
                  <strong>Police Station</strong>
                  <br />
                  {p.properties.NAME}
                  <br />
                  {p.properties.ADDRESS}
                </Popup>
              </CircleMarker>
            );
          })}

        {/* HOSPITALS (GREEN) */}
        {hospital &&
          hospital.features.map((h) => {
            const [lng, lat] = h.geometry.coordinates;

            return (
              <CircleMarker
                key={h.properties.OBJECTID}
                center={[lat, lng]}
                radius={5}
                pathOptions={{
                  color: 'white',
                  weight: 1,
                  fillColor: 'green',
                  fillOpacity: 1,
                }}
              >
                <Popup>
                  <strong>Hospital</strong>
                  <br />
                  {h.properties.NAME}
                  <br />
                  {h.properties.ADDRESS}
                </Popup>
              </CircleMarker>
            );
          })}
      </MapContainer>
    </div>
  );
}
