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

export interface RoadSegment {
  name: string
  distance_miles: number
  distance_meters: number
  duration_seconds: number
  highway_refs: string[]
  is_major_road: boolean
  road_type: 'motorway' | 'highway' | 'local' | 'unnamed'
  instruction?: string
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
  low_miles?: number
  moderate_miles?: number
  high_miles?: number
  severe_miles?: number
  no_travel_miles?: number
  safety_score?: number
  estimated_fuel_gallons?: number
  estimated_fuel_cost?: number
  average_risk_score?: number
  has_no_travel?: boolean
  has_unknown_weather?: boolean
  is_complete_analysis?: boolean
  is_recommended?: boolean
  recommendation_status?: string
  recommendation_label?: string
  rank?: number
  roads_used?: RoadSegment[]
  roads_travel_order?: string[]
  major_roads?: RoadSegment[]
  highway_distance_miles?: number
  highway_percentage?: number
  toll_distance_miles?: number
  toll_percentage?: number
  has_toll_roads?: boolean
}

export interface LocationInfo {
  name: string
  coordinates: [number, number]
}

export interface SevereAlert {
  route_id: string
  route_name?: string
  checkpoint_index: number
  distance_from_origin_miles: number
  coordinates: [number, number]
  estimated_arrival_time: string
  risk: string
  wind_speed_mph: number | null
  rain_intensity_in_hr: number | null
  snow_intensity_in_hr: number | null
  load_adjusted_wind_risk?: string
  recommended_action: string
}

export interface RouteTradeoffs {
  safest_route_id: string | null
  shortest_route_id: string | null
  fastest_route_id: string | null
}

export interface RouteAnalysisResponse {
  origin: LocationInfo
  destination: LocationInfo
  departure_datetime: string
  load_weight_lbs: number
  sampling_interval_miles: number
  routes_count: number
  recommended_route_id: string | null
  has_recommended_route: boolean
  warning: string | null
  recommendation_rationale?: string
  tradeoffs?: RouteTradeoffs
  severe_alerts?: SevereAlert[]
  routes: RouteItem[]
  error?: string
}

