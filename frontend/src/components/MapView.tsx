import { useState, useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

export interface HourlyForecastEntry {
  offset_hours: number
  forecast_timestamp: string | null
  wind_speed_mph: number | null
  rain_intensity_in_hr: number | null
  snow_intensity_in_hr: number | null
  wind_risk: string
  rain_risk: string
  snow_risk: string
  load_adjusted_wind_risk: string
  final_risk: string
  weather_status: string
}

export interface Checkpoint {
  checkpoint_index: number
  coordinates: [number, number]
  distance_from_origin_miles: number
  estimated_arrival_time: string
  forecast_timestamp: string | null
  data_source: string
  weather_status: string
  wind_speed_mph: number | null
  rain_intensity_in_hr: number | null
  snow_intensity_in_hr: number | null
  wind_risk: string
  rain_risk: string
  snow_risk: string
  load_adjusted_wind_risk: string
  final_risk: string
  hourly_forecasts?: HourlyForecastEntry[]
}

export interface RouteItem {
  id: string
  name: string
  distance_miles: number
  duration_seconds: number
  geometry: {
    type: string
    coordinates: [number, number][]
  }
  start_coordinates: [number, number]
  destination_coordinates: [number, number]
  checkpoints_count: number
  checkpoints: Checkpoint[]
  severe_miles?: number
  high_miles?: number
  no_travel_miles?: number
  average_risk_score?: number
  has_no_travel?: boolean
  has_unknown_weather?: boolean
  is_complete_analysis?: boolean
  is_recommended?: boolean
  recommendation_status?: string
  recommendation_label?: string
  rank?: number
}

interface MapViewProps {
  routes: RouteItem[]
  selectedRouteId: string
  onSelectRoute: (routeId: string) => void
  selectedCheckpoint: Checkpoint | null
  onSelectCheckpoint: (checkpoint: Checkpoint | null) => void
  originName: string
  destinationName: string
  departureDatetime: string
}

const RISK_COLORS: Record<string, string> = {
  LOW: '#15803D',       // Green
  MODERATE: '#A16207',  // Yellow / Ochre
  HIGH: '#C2410C',      // Orange
  SEVERE: '#DC2626',    // Red
  NO_TRAVEL: '#991B1B', // Dark Red
  UNKNOWN: '#71717A',   // Neutral Gray
}

// Strictly non-blue route colors
const ROUTE_LINE_COLORS = ['#E87532', '#444444', '#A16207']

function formatDateTimeDisplay(date: Date): string {
  try {
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZoneName: 'short',
    })
  } catch {
    return date.toISOString()
  }
}

export function MapView({
  routes,
  selectedRouteId,
  onSelectRoute,
  selectedCheckpoint,
  onSelectCheckpoint,
  originName,
  destinationName,
  departureDatetime,
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markersRef = useRef<maplibregl.Marker[]>([])

  // null = ETA Mode (truck arrival trajectory); number (0-48) = Corridor Forecast Offset Mode
  const [sliderOffset, setSliderOffset] = useState<number | null>(null)

  const selectedRoute = routes.find((r) => r.id === selectedRouteId) || routes[0]

  const depDate = new Date(departureDatetime)
  const isDepDateValid = !isNaN(depDate.getTime())
  const validDepDate = isDepDateValid ? depDate : new Date()

  const activeSliderDate =
    sliderOffset !== null
      ? new Date(validDepDate.getTime() + sliderOffset * 3600 * 1000)
      : null

  // Helper to get active weather and risk for a checkpoint depending on slider offset
  const getCheckpointActiveData = (cp: Checkpoint) => {
    if (sliderOffset === null) {
      return {
        risk: cp.final_risk,
        wind_speed_mph: cp.wind_speed_mph,
        rain_intensity_in_hr: cp.rain_intensity_in_hr,
        snow_intensity_in_hr: cp.snow_intensity_in_hr,
        wind_risk: cp.wind_risk,
        rain_risk: cp.rain_risk,
        snow_risk: cp.snow_risk,
        load_adjusted_wind_risk: cp.load_adjusted_wind_risk,
        forecast_timestamp: cp.forecast_timestamp,
        weather_status: cp.weather_status,
        is_eta_mode: true,
      }
    }

    const entry = cp.hourly_forecasts?.find((h) => h.offset_hours === sliderOffset)
    if (entry && entry.weather_status === 'AVAILABLE') {
      return {
        risk: entry.final_risk,
        wind_speed_mph: entry.wind_speed_mph,
        rain_intensity_in_hr: entry.rain_intensity_in_hr,
        snow_intensity_in_hr: entry.snow_intensity_in_hr,
        wind_risk: entry.wind_risk,
        rain_risk: entry.rain_risk,
        snow_risk: entry.snow_risk,
        load_adjusted_wind_risk: entry.load_adjusted_wind_risk,
        forecast_timestamp: entry.forecast_timestamp,
        weather_status: 'AVAILABLE',
        is_eta_mode: false,
      }
    }

    return {
      risk: 'UNKNOWN',
      wind_speed_mph: null,
      rain_intensity_in_hr: null,
      snow_intensity_in_hr: null,
      wind_risk: 'UNKNOWN',
      rain_risk: 'UNKNOWN',
      snow_risk: 'UNKNOWN',
      load_adjusted_wind_risk: 'UNKNOWN',
      forecast_timestamp: null,
      weather_status: 'UNAVAILABLE',
      is_eta_mode: false,
    }
  }

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return

    try {
      const cartoKey = import.meta.env.VITE_CARTO_API_KEY
      const customTileUrl = import.meta.env.VITE_MAP_TILE_URL

      // Determine raster tile source:
      // 1. If custom tile URL is specified, use it.
      // 2. If CARTO API key is provided, use CARTO Light with key.
      // 3. Otherwise default to OpenStreetMap standard tiles (requires no API key for dev).
      let tileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
      let attribution = '© OpenStreetMap contributors'

      if (customTileUrl) {
        tileUrl = customTileUrl
      } else if (cartoKey) {
        tileUrl = `https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png?key=${cartoKey}`
        attribution = '© OpenStreetMap contributors, © CARTO'
      }

      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: {
          version: 8,
          sources: {
            'neutral-tiles': {
              type: 'raster',
              tiles: [tileUrl],
              tileSize: 256,
              attribution: attribution,
              maxzoom: 19,
            },
          },
          layers: [
            {
              id: 'neutral-base',
              type: 'raster',
              source: 'neutral-tiles',
              minzoom: 0,
              maxzoom: 19,
              paint: {
                'raster-saturation': -1.0,
                'raster-contrast': 0.05,
              },
            },
          ],
        },
        center: [8.55, 49.45],
        zoom: 10,
        attributionControl: false,
      })

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')

      mapRef.current = map

      return () => {
        map.remove()
        mapRef.current = null
      }
    } catch (err) {
      console.error('Failed to initialize MapLibre GL map:', err)
    }
  }, [])

  // Update Route Polylines and Corridor on Map
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const updateLayers = () => {
      // Clear old route sources and layers
      routes.forEach((route) => {
        const lineLayerId = `layer-line-${route.id}`
        const casingLayerId = `layer-casing-${route.id}`
        const sourceId = `source-${route.id}`

        if (map.getLayer(lineLayerId)) map.removeLayer(lineLayerId)
        if (map.getLayer(casingLayerId)) map.removeLayer(casingLayerId)
        if (map.getSource(sourceId)) map.removeSource(sourceId)
      })

      if (map.getLayer('layer-corridor-highlight')) map.removeLayer('layer-corridor-highlight')
      if (map.getSource('source-corridor-highlight')) map.removeSource('source-corridor-highlight')

      if (routes.length === 0) return

      // Add sources and layers for each route
      routes.forEach((route, idx) => {
        const isSelected = route.id === selectedRouteId
        const sourceId = `source-${route.id}`
        const lineLayerId = `layer-line-${route.id}`
        const casingLayerId = `layer-casing-${route.id}`
        const baseColor = ROUTE_LINE_COLORS[idx % ROUTE_LINE_COLORS.length]

        if (!route.geometry || !route.geometry.coordinates || route.geometry.coordinates.length === 0) {
          return
        }

        map.addSource(sourceId, {
          type: 'geojson',
          data: {
            type: 'Feature',
            properties: { id: route.id, name: route.name },
            geometry: route.geometry,
          },
        })

        // Outer casing for selected route
        if (isSelected) {
          map.addLayer({
            id: casingLayerId,
            type: 'line',
            source: sourceId,
            layout: {
              'line-join': 'round',
              'line-cap': 'round',
            },
            paint: {
              'line-color': '#222222',
              'line-width': 8,
              'line-opacity': 0.85,
            },
          })
        }

        // Main route line
        map.addLayer({
          id: lineLayerId,
          type: 'line',
          source: sourceId,
          layout: {
            'line-join': 'round',
            'line-cap': 'round',
          },
          paint: {
            'line-color': isSelected ? baseColor : '#666666',
            'line-width': isSelected ? 5 : 3,
            'line-opacity': isSelected ? 1.0 : 0.45,
          },
        })

        // Click to select route
        map.on('click', lineLayerId, () => {
          onSelectRoute(route.id)
        })

        map.on('mouseenter', lineLayerId, () => {
          map.getCanvas().style.cursor = 'pointer'
        })
        map.on('mouseleave', lineLayerId, () => {
          map.getCanvas().style.cursor = ''
        })
      })

      // Add Weather Corridor Buffer Layer along the selected route
      if (selectedRoute && selectedRoute.checkpoints && selectedRoute.checkpoints.length > 0) {
        const coords = selectedRoute.geometry.coordinates
        if (coords.length > 1) {
          const corridorFeatures = []
          const cps = selectedRoute.checkpoints

          for (let i = 0; i < cps.length; i++) {
            const cp = cps[i]
            const activeData = getCheckpointActiveData(cp)
            const riskColor = RISK_COLORS[activeData.risk] || RISK_COLORS.UNKNOWN

            const nextCp = cps[i + 1]
            const pt1 = cp.coordinates
            const pt2 = nextCp ? nextCp.coordinates : pt1

            corridorFeatures.push({
              type: 'Feature',
              properties: {
                risk: activeData.risk,
                color: riskColor,
              },
              geometry: {
                type: 'LineString',
                coordinates: [pt1, pt2],
              },
            })
          }

          map.addSource('source-corridor-highlight', {
            type: 'geojson',
            data: {
              type: 'FeatureCollection',
              features: corridorFeatures as any,
            },
          })

          map.addLayer(
            {
              id: 'layer-corridor-highlight',
              type: 'line',
              source: 'source-corridor-highlight',
              layout: {
                'line-join': 'round',
                'line-cap': 'round',
              },
              paint: {
                'line-color': ['get', 'color'],
                'line-width': 14,
                'line-opacity': 0.4,
              },
            },
            `layer-casing-${selectedRoute.id}`
          )
        }
      }

      // Fit map bounds to encompass the selected route
      if (selectedRoute?.geometry?.coordinates?.length) {
        const bounds = new maplibregl.LngLatBounds()
        selectedRoute.geometry.coordinates.forEach((coord) => {
          bounds.extend(coord as [number, number])
        })
        map.fitBounds(bounds, { padding: 45, maxZoom: 13, duration: 800 })
      }
    }

    if (map.isStyleLoaded()) {
      updateLayers()
    } else {
      map.once('load', updateLayers)
    }
  }, [routes, selectedRouteId, onSelectRoute, selectedRoute, sliderOffset])

  // Update Markers (Start, Destination, and Checkpoints)
  useEffect(() => {
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []

    const map = mapRef.current
    if (!map || !selectedRoute) return

    // 1. Origin Marker
    if (selectedRoute.start_coordinates) {
      const startEl = document.createElement('div')
      startEl.className = 'map-marker-pin marker-start'
      startEl.innerHTML = '<span>START</span>'
      startEl.title = `Origin: ${originName}`

      const startMarker = new maplibregl.Marker({ element: startEl })
        .setLngLat(selectedRoute.start_coordinates)
        .addTo(map)
      markersRef.current.push(startMarker)
    }

    // 2. Destination Marker
    if (selectedRoute.destination_coordinates) {
      const destEl = document.createElement('div')
      destEl.className = 'map-marker-pin marker-dest'
      destEl.innerHTML = '<span>DEST</span>'
      destEl.title = `Destination: ${destinationName}`

      const destMarker = new maplibregl.Marker({ element: destEl })
        .setLngLat(selectedRoute.destination_coordinates)
        .addTo(map)
      markersRef.current.push(destMarker)
    }

    // 3. Checkpoint Markers for the Selected Route
    if (selectedRoute.checkpoints) {
      selectedRoute.checkpoints.forEach((cp) => {
        const isSelected = selectedCheckpoint?.checkpoint_index === cp.checkpoint_index
        const cpEl = document.createElement('div')
        const activeData = getCheckpointActiveData(cp)
        const riskColor = RISK_COLORS[activeData.risk] || RISK_COLORS.UNKNOWN

        cpEl.className = `map-checkpoint-marker ${isSelected ? 'selected' : ''}`
        cpEl.style.backgroundColor = riskColor
        cpEl.innerHTML = `<span>${cp.checkpoint_index}</span>`
        cpEl.setAttribute('role', 'button')
        cpEl.setAttribute('tabindex', '0')

        const modeDesc =
          sliderOffset === null
            ? `ETA: ${new Date(cp.estimated_arrival_time).toLocaleTimeString()}`
            : `Snapshot: +${sliderOffset}h`

        const labelText = `Checkpoint ${cp.checkpoint_index} (${cp.distance_from_origin_miles} mi) - ${modeDesc} - Risk: ${activeData.risk}`
        cpEl.title = labelText
        cpEl.setAttribute('aria-label', labelText)

        cpEl.addEventListener('click', (e) => {
          e.stopPropagation()
          onSelectCheckpoint(cp)
        })

        cpEl.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            e.stopPropagation()
            onSelectCheckpoint(cp)
          }
        })

        const marker = new maplibregl.Marker({ element: cpEl })
          .setLngLat(cp.coordinates)
          .addTo(map)

        markersRef.current.push(marker)
      })
    }
  }, [
    selectedRoute,
    selectedCheckpoint,
    onSelectCheckpoint,
    originName,
    destinationName,
    sliderOffset,
  ])

  const inspectorData = selectedCheckpoint ? getCheckpointActiveData(selectedCheckpoint) : null

  return (
    <div className="map-view-wrapper">
      <div className="map-header">
        <div className="map-title-row">
          <h3>Trip Route & Weather Corridor Map</h3>
          <span className="active-route-badge">
            Viewing: {selectedRoute?.name || 'Selected Route'}
          </span>
        </div>
        <p className="map-subtitle">
          Showing road geometry, weather corridor risk halo, and interactive checkpoints.
        </p>
      </div>

      {/* TASK 1: 0–48 Hour Forecast Time Slider Component */}
      <div className="forecast-slider-container">
        <div className="slider-header-row">
          <div className="slider-label-group">
            <span className="slider-title">Trip Corridor Forecast Timeline (0–48h)</span>
            <div className="slider-mode-indicator">
              {sliderOffset === null ? (
                <span className="mode-badge-eta">
                  📍 Active: Checkpoint Arrival Times (Trajectory Forecast)
                </span>
              ) : (
                <span className="mode-badge-snapshot">
                  ⏱ Active: +{sliderOffset}h from Departure (
                  {activeSliderDate ? formatDateTimeDisplay(activeSliderDate) : ''})
                </span>
              )}
            </div>
          </div>

          <div className="slider-quick-buttons">
            <button
              type="button"
              className={`slider-btn ${sliderOffset === null ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(null)}
              title="View weather forecasted at each checkpoint's estimated arrival time"
            >
              📍 Checkpoint ETAs
            </button>
            <button
              type="button"
              className={`slider-btn ${sliderOffset === 0 ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(0)}
            >
              +0h (Departure)
            </button>
            <button
              type="button"
              className={`slider-btn ${sliderOffset === 6 ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(6)}
            >
              +6h
            </button>
            <button
              type="button"
              className={`slider-btn ${sliderOffset === 12 ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(12)}
            >
              +12h
            </button>
            <button
              type="button"
              className={`slider-btn ${sliderOffset === 24 ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(24)}
            >
              +24h
            </button>
            <button
              type="button"
              className={`slider-btn ${sliderOffset === 48 ? 'btn-active' : ''}`}
              onClick={() => setSliderOffset(48)}
            >
              +48h
            </button>
          </div>
        </div>

        <div className="slider-control-row">
          <input
            type="range"
            min="0"
            max="48"
            step="1"
            value={sliderOffset ?? 0}
            onChange={(e) => setSliderOffset(Number(e.target.value))}
            aria-label="Trip corridor forecast timeline offset in hours"
            aria-valuemin={0}
            aria-valuemax={48}
            aria-valuenow={sliderOffset ?? 0}
            aria-valuetext={sliderOffset === null ? 'Active: Estimated Arrival Time Trajectory' : `+${sliderOffset} hours after departure`}
            className="forecast-range-slider"
          />
          <div className="slider-ticks-row">
            <span>+0h (Departure)</span>
            <span>+12h</span>
            <span>+24h (Day 1)</span>
            <span>+36h</span>
            <span>+48h (Day 2)</span>
          </div>
        </div>

        {sliderOffset !== null && (
          <p className="slider-context-note">
            Visualizing weather along the corridor at <strong>+{sliderOffset}h</strong> relative to
            departure ({activeSliderDate ? formatDateTimeDisplay(activeSliderDate) : ''}).
            Route-ranking and checkpoint ETAs remain fixed to the truck schedule.
          </p>
        )}
      </div>

      {/* Map Canvas */}
      <div className="map-canvas-container" ref={mapContainerRef} />

      {/* Weather Corridor Legend */}
      <div className="corridor-legend">
        <span className="legend-label">Corridor Risk Legend:</span>
        <div className="legend-items">
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.LOW }} /> Low
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.MODERATE }} /> Moderate
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.HIGH }} /> High
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.SEVERE }} /> Severe
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.NO_TRAVEL }} /> No Travel
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: RISK_COLORS.UNKNOWN }} /> Unknown
          </span>
        </div>
      </div>
      <p className="corridor-disclosure">
        * Note: The route corridor highlights estimated risk based on weather sampled at periodic
        checkpoints along the truck path, not a continuous weather observation.
      </p>

      {/* Selected Checkpoint Detail Inspection Card */}
      {selectedCheckpoint && inspectorData && (
        <div className="checkpoint-inspector-card">
          <div className="inspector-header">
            <h4>
              Checkpoint {selectedCheckpoint.checkpoint_index} Details (
              {selectedCheckpoint.distance_from_origin_miles} miles from origin)
            </h4>
            <button
              type="button"
              className="inspector-close-btn"
              onClick={() => onSelectCheckpoint(null)}
            >
              ✕
            </button>
          </div>

          {inspectorData.weather_status === 'UNAVAILABLE' ? (
            <div className="inspector-unavailable-alert">
              ⚠️ Forecast unavailable for this time.
            </div>
          ) : (
            <div className="inspector-grid">
              <div className="inspector-item">
                <span className="ins-label">Estimated Arrival Time (ETA)</span>
                <span className="ins-value">
                  {formatDateTimeDisplay(new Date(selectedCheckpoint.estimated_arrival_time))}
                </span>
                <span className="ins-sub">
                  UTC: {selectedCheckpoint.estimated_arrival_time.slice(11, 16)}Z
                </span>
              </div>

              <div className="inspector-item">
                <span className="ins-label">
                  {sliderOffset === null
                    ? 'Matched Forecast Hour'
                    : `Forecast at +${sliderOffset}h`}
                </span>
                <span className="ins-value">
                  {inspectorData.forecast_timestamp || 'Unavailable'}
                </span>
                <span className="ins-sub">Source: {selectedCheckpoint.data_source}</span>
              </div>

              <div className="inspector-item">
                <span className="ins-label">Wind Condition</span>
                <span className="ins-value">
                  {inspectorData.wind_speed_mph !== null
                    ? `${inspectorData.wind_speed_mph} mph`
                    : 'N/A'}{' '}
                  <span className={`risk-badge badge-${inspectorData.wind_risk.toLowerCase()}`}>
                    {inspectorData.wind_risk}
                  </span>
                </span>
                <span className="ins-sub">
                  Load-adjusted: <strong>{inspectorData.load_adjusted_wind_risk}</strong>
                </span>
              </div>

              <div className="inspector-item">
                <span className="ins-label">Precipitation (Rain / Snow)</span>
                <span className="ins-value">
                  Rain: {inspectorData.rain_intensity_in_hr ?? 0} in/hr | Snow:{' '}
                  {inspectorData.snow_intensity_in_hr ?? 0} in/hr
                </span>
                <span className="ins-sub">
                  Rain: {inspectorData.rain_risk} | Snow: {inspectorData.snow_risk}
                </span>
              </div>

              <div className="inspector-item inspector-highlight">
                <span className="ins-label">
                  {sliderOffset === null
                    ? 'Combined Checkpoint Risk (at ETA)'
                    : `Corridor Risk (at +${sliderOffset}h)`}
                </span>
                <span
                  className={`risk-badge badge-${inspectorData.risk.toLowerCase().replace('_', '-')}`}
                >
                  {inspectorData.risk}
                </span>
                <span className="ins-sub">Status: {inspectorData.weather_status}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
