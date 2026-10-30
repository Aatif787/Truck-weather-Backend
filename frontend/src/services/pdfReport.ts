import { jsPDF } from 'jspdf'
import type { RouteAnalysisResponse, RouteItem } from '../types'

interface PdfReportOptions {
  data: RouteAnalysisResponse
  selectedRoute: RouteItem
  fuelPrice: number
  fuelMpg: number
}

function formatDuration(seconds: number): string {
  const totalMins = Math.round(seconds / 60)
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  if (hrs > 0) return `${hrs}h ${mins}m`
  return `${mins}m`
}

function getRiskRgb(risk: string): [number, number, number] {
  switch (risk.toUpperCase()) {
    case 'LOW':
      return [21, 128, 61]
    case 'MODERATE':
      return [161, 98, 7]
    case 'HIGH':
      return [194, 65, 12]
    case 'SEVERE':
      return [220, 38, 38]
    case 'NO_TRAVEL':
      return [153, 27, 27]
    default:
      return [113, 113, 122]
  }
}

export function generateTripReportPdf({
  data,
  selectedRoute,
  fuelPrice,
  fuelMpg,
}: PdfReportOptions): void {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'pt',
    format: 'a4',
  })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 40
  const contentWidth = pageWidth - margin * 2
  let y = margin

  function checkPageBreak(requiredHeight: number) {
    if (y + requiredHeight > pageHeight - margin - 30) {
      doc.addPage()
      y = margin
      renderHeaderBar(true)
    }
  }

  function renderHeaderBar(isContinuation = false) {
    // Top Brand Accent Stripe (Safety Orange, zero blue)
    doc.setFillColor(232, 117, 50)
    doc.rect(margin, y, contentWidth, 4, 'F')
    y += 14

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(14)
    doc.setTextColor(24, 24, 27) // Charcoal
    doc.text('SPOTTER FREIGHT | WEATHER-AWARE DISPATCH REPORT', margin, y)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(113, 113, 122)
    const subText = isContinuation
      ? `Continuation | ${data.origin.name.split(',')[0]} ➔ ${data.destination.name.split(',')[0]}`
      : `Generated: ${new Date().toUTCString()} | Class 8 Commercial Analysis`
    doc.text(subText, pageWidth - margin, y, { align: 'right' })

    y += 16
    doc.setDrawColor(229, 229, 226)
    doc.setLineWidth(0.75)
    doc.line(margin, y, pageWidth - margin, y)
    y += 18
  }

  // Page 1 Header
  renderHeaderBar(false)

  // 1. TRIP DISPATCH METADATA CARD
  doc.setFillColor(249, 249, 248)
  doc.setDrawColor(229, 229, 226)
  doc.roundedRect(margin, y, contentWidth, 72, 3, 3, 'FD')

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(24, 24, 27)

  // Column 1: Origin & Destination
  doc.text('ORIGIN:', margin + 14, y + 18)
  doc.setFont('helvetica', 'normal')
  doc.text(data.origin.name.length > 35 ? data.origin.name.slice(0, 35) + '...' : data.origin.name, margin + 65, y + 18)

  doc.setFont('helvetica', 'bold')
  doc.text('DESTINATION:', margin + 14, y + 36)
  doc.setFont('helvetica', 'normal')
  doc.text(data.destination.name.length > 32 ? data.destination.name.slice(0, 32) + '...' : data.destination.name, margin + 90, y + 36)

  doc.setFont('helvetica', 'bold')
  doc.text('DEPARTURE:', margin + 14, y + 54)
  doc.setFont('helvetica', 'normal')
  doc.text(new Date(data.departure_datetime).toLocaleString(), margin + 80, y + 54)

  // Column 2: Parameters
  const col2X = margin + 300
  doc.setFont('helvetica', 'bold')
  doc.text('CARGO WEIGHT:', col2X, y + 18)
  doc.setFont('helvetica', 'normal')
  doc.text(`${data.load_weight_lbs.toLocaleString()} lbs`, col2X + 85, y + 18)

  doc.setFont('helvetica', 'bold')
  doc.text('WEATHER SAMPLE:', col2X, y + 36)
  doc.setFont('helvetica', 'normal')
  doc.text(`Every ${data.sampling_interval_miles} mi (ETA matched)`, col2X + 95, y + 36)

  doc.setFont('helvetica', 'bold')
  doc.text('FUEL BASELINE:', col2X, y + 54)
  doc.setFont('helvetica', 'normal')
  doc.text(`$${fuelPrice.toFixed(2)}/gal @ ${fuelMpg.toFixed(1)} MPG`, col2X + 85, y + 54)

  y += 86

  // 2. SELECTED ROUTE & ALGORITHMIC RECOMMENDATION RATIONALE
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(24, 24, 27)
  doc.text('DISPATCH RECOMMENDATION & SAFETY EVALUATION', margin, y)
  y += 14

  doc.setFillColor(254, 249, 245) // Warm light tint
  doc.setDrawColor(242, 166, 90) // Soft orange border
  doc.roundedRect(margin, y, contentWidth, 54, 3, 3, 'FD')

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(194, 65, 12) // Safety Dark Orange
  doc.text(`RECOMMENDED ROUTE: ${selectedRoute.name} (${selectedRoute.recommendation_label || 'Safest Path'})`, margin + 12, y + 16)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(40, 40, 40)
  const rationaleText = data.recommendation_rationale ||
    `${selectedRoute.name} minimizes severe weather exposure with ${selectedRoute.severe_miles || 0} severe miles and ${selectedRoute.high_miles || 0} high-risk miles.`
  const splitRationale = doc.splitTextToSize(rationaleText, contentWidth - 24)
  doc.text(splitRationale, margin + 12, y + 30)

  y += 66

  // 2b. ROADS & HIGHWAYS TRAVERSED
  if (selectedRoute.roads_used && selectedRoute.roads_used.length > 0) {
    checkPageBreak(55)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9.5)
    doc.setTextColor(24, 24, 27)
    const hwSummary = selectedRoute.highway_distance_miles !== undefined && selectedRoute.highway_distance_miles > 0
      ? ` • ${selectedRoute.highway_distance_miles.toFixed(1)} mi on Major Highways (${selectedRoute.highway_percentage}%)`
      : ''
    const tollSummary = selectedRoute.has_toll_roads
      ? ` • ${selectedRoute.toll_distance_miles?.toFixed(1)} mi Toll Roads`
      : ' • Toll-Free Corridor'
    doc.text(`ROADS & HIGHWAYS USED (TRAVEL ORDER)${hwSummary}${tollSummary}:`, margin, y)
    y += 12

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(70, 70, 70)
    const roadChain = selectedRoute.roads_used.map((r) => {
      const tag = r.is_major_road ? `[${r.name}]` : r.name
      return `${tag} (${r.distance_miles.toFixed(1)} mi)`
    }).join('  →  ')

    const splitChain = doc.splitTextToSize(roadChain, contentWidth)
    doc.text(splitChain, margin, y)
    y += (splitChain.length * 9.5) + 12
  }

  // 3. ROUTE COMPARISON MATRIX TABLE
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(24, 24, 27)
  doc.text('ROUTE ALTERNATIVES COMPARISON (MEASURED & MODELED)', margin, y)
  y += 14

  // Table Header
  const headers = ['Route Name', 'Distance', 'Duration', 'Safety Score', 'High Risk', 'Severe', 'Est Fuel ($)']
  const colWidths = [140, 60, 60, 65, 60, 55, 75]
  
  doc.setFillColor(24, 24, 27) // Dark charcoal header
  doc.rect(margin, y, contentWidth, 20, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(255, 255, 255)

  let curX = margin
  headers.forEach((h, idx) => {
    doc.text(h, curX + 6, y + 13)
    curX += colWidths[idx]
  })
  y += 20

  // Table Rows
  data.routes.forEach((r, rIdx) => {
    const isSelected = r.id === selectedRoute.id
    if (isSelected) {
      doc.setFillColor(254, 243, 235) // Light orange highlight
    } else if (rIdx % 2 === 1) {
      doc.setFillColor(249, 249, 248)
    } else {
      doc.setFillColor(255, 255, 255)
    }
    doc.rect(margin, y, contentWidth, 22, 'F')
    doc.setDrawColor(229, 229, 226)
    doc.line(margin, y + 22, margin + contentWidth, y + 22)

    doc.setFont('helvetica', isSelected ? 'bold' : 'normal')
    doc.setFontSize(8)
    doc.setTextColor(24, 24, 27)

    const estGallons = (r.distance_miles / fuelMpg)
    const estCost = estGallons * fuelPrice
    const safetyScore = r.safety_score !== undefined ? `${r.safety_score.toFixed(0)}/100` : 'N/A'

    const rowData = [
      (isSelected ? '★ ' : '') + r.name.slice(0, 22),
      `${r.distance_miles.toFixed(1)} mi`,
      formatDuration(r.duration_seconds),
      safetyScore,
      `${(r.high_miles || 0).toFixed(1)} mi`,
      `${(r.severe_miles || 0).toFixed(1)} mi`,
      `$${estCost.toFixed(2)} (est)`
    ]

    curX = margin
    rowData.forEach((val, cIdx) => {
      if (cIdx === 3 && r.safety_score !== undefined) {
        if (r.safety_score >= 80) doc.setTextColor(21, 128, 61)
        else if (r.safety_score >= 50) doc.setTextColor(161, 98, 7)
        else doc.setTextColor(220, 38, 38)
      } else {
        doc.setTextColor(24, 24, 27)
      }
      doc.text(val, curX + 6, y + 14)
      curX += colWidths[cIdx]
    })
    y += 22
  })

  y += 18

  // 4. SEVERE WEATHER & NO-TRAVEL ALERTS (IF ANY)
  const routeSevereAlerts = (data.severe_alerts || []).filter(
    (a) => a.route_id === selectedRoute.id
  )

  if (routeSevereAlerts.length > 0) {
    checkPageBreak(80)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(185, 28, 28) // Red
    doc.text(`SEVERE WEATHER ALERTS ALONG ${selectedRoute.name.toUpperCase()} (${routeSevereAlerts.length} CHECKPOINTS)`, margin, y)
    y += 14

    routeSevereAlerts.forEach((alert) => {
      checkPageBreak(50)
      const isNoTravel = alert.risk === 'NO_TRAVEL'
      doc.setFillColor(isNoTravel ? 254 : 255, isNoTravel ? 242 : 247, isNoTravel ? 242 : 237)
      doc.setDrawColor(isNoTravel ? 153 : 220, isNoTravel ? 27 : 38, isNoTravel ? 27 : 38)
      doc.roundedRect(margin, y, contentWidth, 42, 2, 2, 'FD')

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(8.5)
      doc.setTextColor(isNoTravel ? 153 : 220, isNoTravel ? 27 : 38, isNoTravel ? 27 : 38)
      doc.text(`[${alert.risk}] Checkpoint #${alert.checkpoint_index + 1} (${alert.distance_from_origin_miles.toFixed(1)} mi) | Forecast ETA: ${new Date(alert.estimated_arrival_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`, margin + 10, y + 14)

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7.5)
      doc.setTextColor(50, 50, 50)
      const condStr = `Wind: ${alert.wind_speed_mph || 0} mph | Rain: ${alert.rain_intensity_in_hr || 0} in/hr | Snow: ${alert.snow_intensity_in_hr || 0} in/hr`
      doc.text(condStr, margin + 10, y + 26)

      doc.setFont('helvetica', 'bold')
      doc.setTextColor(24, 24, 27)
      doc.text(`Action: ${alert.recommended_action}`, margin + 10, y + 36)

      y += 48
    })
    y += 6
  }

  // 5. DETAILED CHECKPOINT FORECAST TABLE
  checkPageBreak(120)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(24, 24, 27)
  doc.text(`CHECKPOINT WEATHER ITINERARY (${selectedRoute.name} - ${selectedRoute.checkpoints.length} CHECKPOINTS)`, margin, y)
  y += 14

  const cpHeaders = ['#', 'Distance', 'Forecast ETA', 'Wind (mph)', 'Rain (in/h)', 'Snow (in/h)', 'Risk Level']
  const cpColWidths = [30, 75, 110, 75, 75, 75, 75]

  doc.setFillColor(60, 60, 60)
  doc.rect(margin, y, contentWidth, 18, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(255, 255, 255)

  let cpCurX = margin
  cpHeaders.forEach((h, idx) => {
    doc.text(h, cpCurX + 5, y + 12)
    cpCurX += cpColWidths[idx]
  })
  y += 18

  selectedRoute.checkpoints.forEach((cp, idx) => {
    checkPageBreak(20)
    if (y === margin) {
      // Re-render subheader on new page
      doc.setFillColor(60, 60, 60)
      doc.rect(margin, y, contentWidth, 18, 'F')
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(7.5)
      doc.setTextColor(255, 255, 255)
      let rx = margin
      cpHeaders.forEach((h, hIdx) => {
        doc.text(h, rx + 5, y + 12)
        rx += cpColWidths[hIdx]
      })
      y += 18
    }

    if (idx % 2 === 1) {
      doc.setFillColor(249, 249, 248)
      doc.rect(margin, y, contentWidth, 18, 'F')
    }
    doc.setDrawColor(235, 235, 232)
    doc.line(margin, y + 18, margin + contentWidth, y + 18)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(24, 24, 27)

    const etaStr = cp.estimated_arrival_time
      ? new Date(cp.estimated_arrival_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' })
      : 'N/A'

    const row = [
      `CP ${cp.checkpoint_index + 1}`,
      `${cp.distance_from_origin_miles.toFixed(1)} mi`,
      etaStr,
      cp.wind_speed_mph !== null ? `${cp.wind_speed_mph.toFixed(0)} mph` : 'N/A',
      cp.rain_intensity_in_hr !== null ? `${cp.rain_intensity_in_hr.toFixed(2)} in/h` : '0.00',
      cp.snow_intensity_in_hr !== null ? `${cp.snow_intensity_in_hr.toFixed(2)} in/h` : '0.00',
      cp.final_risk || 'UNKNOWN',
    ]

    cpCurX = margin
    row.forEach((cVal, cIdx) => {
      if (cIdx === 6) {
        const rgb = getRiskRgb(cp.final_risk || 'UNKNOWN')
        doc.setTextColor(rgb[0], rgb[1], rgb[2])
        doc.setFont('helvetica', 'bold')
      } else {
        doc.setTextColor(24, 24, 27)
        doc.setFont('helvetica', 'normal')
      }
      doc.text(cVal, cpCurX + 5, y + 12)
      cpCurX += cpColWidths[cIdx]
    })
    y += 18
  })

  // 6. METEOROLOGICAL DISCLOSURE & DATA LIMITATIONS
  checkPageBreak(75)
  y += 14
  doc.setFillColor(245, 245, 242)
  doc.setDrawColor(220, 220, 215)
  doc.roundedRect(margin, y, contentWidth, 54, 2, 2, 'FD')

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(60, 60, 60)
  doc.text('METEOROLOGICAL NOTICE & OPERATIONAL DISCLAIMER', margin + 8, y + 14)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.5)
  doc.setTextColor(90, 90, 90)
  const disclaimer = [
    '• Forecast Source: Open-Meteo Deterministic Weather Forecast (0-48h). Forecast data is sampled at estimated waypoint arrival times (ETAs).',
    '• Routing Engine: OpenRouteService Heavy Goods Vehicle (HGV) profile with commercial axle and dimension parameters.',
    '• Fuel & Cost Estimates: Modeled planning figures based on Class 8 HGV baseline consumption ($' + fuelPrice.toFixed(2) + '/gal, ' + fuelMpg.toFixed(1) + ' MPG); not engine ECM telemetry.',
    '• Safety Notice: Weather conditions can evolve rapidly. Drivers and dispatchers must continuously monitor local DOT road conditions and advisories.'
  ]
  disclaimer.forEach((line, lIdx) => {
    doc.text(line, margin + 8, y + 24 + lIdx * 8)
  })

  // Footer on all pages
  const totalPages = doc.getNumberOfPages()
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(140, 140, 140)
    doc.text(
      `Spotter Weather-Aware Routing Engine | Page ${i} of ${totalPages}`,
      pageWidth / 2,
      pageHeight - 20,
      { align: 'center' }
    )
  }

  // Save the PDF
  const filename = `Spotter-Trip-Report-${data.origin.name.split(',')[0].trim()}-to-${data.destination.name.split(',')[0].trim()}.pdf`
    .replace(/[^a-zA-Z0-9-_\.]/g, '_')
  doc.save(filename)
}

