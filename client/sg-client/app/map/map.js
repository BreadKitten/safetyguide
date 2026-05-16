'use client';

import { useEffect, useRef } from 'react';
import * as d3 from 'd3';

export default function Map() {
  const svgRef = useRef(null);

  useEffect(() => {
    const width = 1200;
    const height = 800;

    const svg = d3.select(svgRef.current);

    svg.selectAll('*').remove();

    svg
      .attr('width', width)
      .attr('height', height)
      .style('background', '#dbeafe');

    const g = svg.append('g');

    // Zoom + Pan
    const zoom = d3
      .zoom()
      .scaleExtent([0.5, 20])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    Promise.all([
      d3.json(
        'https://raw.githubusercontent.com/holtzy/D3-graph-gallery/master/DATA/world.geojson',
      ),
      d3.json('/policestation.geojson'),
      d3.json('/firestation.geojson'),
      d3.json('/wa_counties.geojson'),
    ]).then(([world, policeGeojson, fireGeojson, countyGeojson]) => {
      const combinedFeatures = [
        ...policeGeojson.features,
        ...fireGeojson.features,
      ];

      const combinedGeojson = {
        type: 'FeatureCollection',
        features: combinedFeatures,
      };

      // Projection
      const projection = d3
        .geoAlbersUsa()
        .fitSize([width, height], combinedGeojson);

      const path = d3.geoPath().projection(projection);

      g.selectAll('path')
        .data(world.features)
        .enter()
        .append('path')
        .attr('d', path)
        .attr('fill', d3.rgb(230, 230, 208))
        .attr('stroke', '#9ca3af')
        .attr('stroke-width', 0.5);

      g.selectAll('path').attr('d', path);

      g.selectAll('.fire-circle')
        .data(fireGeojson.features)
        .enter()
        .append('circle')
        .attr('class', 'fire-circle')
        .attr('cx', (d) => projection(d.geometry.coordinates)[0])
        .attr('cy', (d) => projection(d.geometry.coordinates)[1])
        .attr('r', 5)
        .attr('fill', '#dc2626')
        .attr('stroke', 'white')
        .attr('stroke-width', 1.5)
        .append('title');

      g.selectAll('.police-circle')
        .data(policeGeojson.features)
        .enter()
        .append('circle')
        .attr('class', 'police-circle')
        .attr('cx', (d) => projection(d.geometry.coordinates)[0])
        .attr('cy', (d) => projection(d.geometry.coordinates)[1])
        .attr('r', 5)
        .attr('fill', '#2563eb')
        .attr('stroke', 'white')
        .attr('stroke-width', 1.5)
        .append('title');

      g.selectAll('.county')
        .data(countyGeojson.features)
        .enter()
        .append('path')
        .attr('class', 'county')
        .attr('d', path)
        .attr('fill', 'none')
        .attr('stroke', '#374151')
        .attr('stroke-width', 1)
        .attr('opacity', 0.8);
    });
  }, []);

  return (
    <div className='w-full h-screen overflow-hidden'>
      <svg ref={svgRef}></svg>
    </div>
  );
}
