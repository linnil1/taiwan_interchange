<script lang="ts">
	import { browser } from '$app/environment';
	import type { Interchange } from '$lib/types.js';
	import type { Map as LeafletMap, Marker, Polyline } from 'leaflet';
	import { onMount } from 'svelte';

	let {
		selectedInterchange = $bindable(null),
		interchanges = [],
		onInterchangeSelect,
		selectedRampIndex = $bindable(null)
	}: {
		selectedInterchange: Interchange | null;
		interchanges: Interchange[];
		onInterchangeSelect?: (interchange: Interchange) => void;
		selectedRampIndex?: number | null;
	} = $props();

	let map: LeafletMap;
	let mapContainer: HTMLDivElement;
	let allMarkers: Marker[] = [];
	let selectedPaths: Polyline[] = [];
	let L: any; // Leaflet will be loaded dynamically

	onMount(() => {
		if (browser && mapContainer) {
			// Dynamically import Leaflet in the browser
			import('leaflet').then((leafletModule) => {
				L = leafletModule.default;

				// Initialize the map
				map = L.map(mapContainer).setView([23.2, 120.3], 8);

				L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
					maxZoom: 19,
					attribution: '© OpenStreetMap contributors'
				}).addTo(map);

				// Initial markers update will be handled by effects
			});
		}
	});

	// Use effect to watch var changes
	// 1. Use console.log to make svelte track the changed. DO NOT REMOVED
	// 2. Use settimeout to untrack

	// Update markers when interchanges change
	$effect(() => {
		console.log('Interchanges updated', interchanges.length);
		setTimeout(() => {
			updateAllMarkers();
		}, 0);
	});

	// Update selected interchange details when selectedInterchange changes
	$effect(() => {
		console.log('Selected interchange updated', selectedInterchange?.name);
		setTimeout(() => {
			updateSelectedInterchange();
		}, 0);
	});

	// Update polyline styles when selectedRampIndex changes
	$effect(() => {
		console.log('Selected ramp index updated', selectedRampIndex);
		setTimeout(() => {
			updateSelectedInterchange(false); // Redraw with new selection
		}, 0);
	});

	function clearSelectedPaths() {
		selectedPaths.forEach((path) => {
			map.removeLayer(path);
		});
		selectedPaths = [];
	}

	function clearAllMarkers() {
		allMarkers.forEach((marker) => {
			map.removeLayer(marker);
		});
		allMarkers = [];
	}

	function updateAllMarkers() {
		if (!map || !L) return;

		clearAllMarkers();

		// Show markers for all interchanges
		interchanges.forEach((interchange) => {
			const centerLat = (interchange.bounds.min_lat + interchange.bounds.max_lat) / 2;
			const centerLng = (interchange.bounds.min_lng + interchange.bounds.max_lng) / 2;

			const isSelected = selectedInterchange?.id === interchange.id;

			const marker = L.marker([centerLat, centerLng], {
				icon: L.divIcon({
					html: `<div style="background: ${isSelected ? '#ff4444' : '#2196f3'}; color: white; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: bold; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">${interchange.id}</div>`,
					className: 'custom-interchange-marker',
					iconSize: [24, 24],
					iconAnchor: [12, 12]
				})
			}).addTo(map);

			// Add tooltip with interchange index and name
			marker.bindTooltip(`#${interchange.id} ${interchange.name}`, {
				permanent: false,
				direction: 'top',
				offset: [0, -10]
			});

			// Add click handler to marker
			marker.on('click', () => {
				if (onInterchangeSelect) {
					onInterchangeSelect(interchange);
				}
			});

			allMarkers.push(marker);
		});

		// Fit map to show all markers if there are any
		if (allMarkers.length > 0) {
			const group = new L.featureGroup(allMarkers);
			map.fitBounds(group.getBounds(), { padding: [20, 20] });
		}
	}

	function updateSelectedInterchange(autoFocuse = true) {
		if (!map || !L) return;

		// Clear previous selected paths
		clearSelectedPaths();

		// Update marker colors by refreshing all markers
		// updateAllMarkers();

		if (selectedInterchange) {
			// Draw ramp paths for selected interchange
			selectedInterchange.ramps.forEach((ramp, rampIndex) => {
				const rampColor = getColorForRamp(rampIndex);
				const isSelectedRamp = selectedRampIndex === rampIndex;

				ramp.paths.forEach((path) => {
					const coordinates = path.nodes.map((node) => [node.lat, node.lng]);

					const rampPath = L.polyline(coordinates, {
						color: rampColor,
						weight: isSelectedRamp ? 8 : 4,
						opacity: isSelectedRamp ? 1.0 : 0.8
					}).addTo(map);

					// Handle polyline click to focus on ramp instead of showing popup
					rampPath.on('click', () => {
						selectedRampIndex = rampIndex;
					});

					selectedPaths.push(rampPath);
				});
			});

			// Fit map to selected interchange bounds
			const bounds = L.latLngBounds(
				[selectedInterchange.bounds.min_lat, selectedInterchange.bounds.min_lng],
				[selectedInterchange.bounds.max_lat, selectedInterchange.bounds.max_lng]
			);
			if (autoFocuse) map.fitBounds(bounds, { padding: [20, 20] });
		}
	}

	function getColorForRamp(index: number) {
		const colors = [
			'#f44336',
			'#e91e63',
			'#9c27b0',
			'#673ab7',
			'#3f51b5',
			'#2196f3',
			'#03a9f4',
			'#00bcd4',
			'#009688',
			'#4caf50',
			'#8bc34a',
			'#cddc39',
			'#ffeb3b',
			'#ffc107',
			'#ff9800',
			'#ff5722',
			'#795548',
			'#9e9e9e',
			'#607d8b'
		];
		return colors[index % colors.length];
	}

	function fitToRamp(rampIndex: number) {
		if (
			!map ||
			!L ||
			!selectedInterchange ||
			rampIndex < 0 ||
			rampIndex >= selectedInterchange.ramps.length
		)
			return;

		const ramp = selectedInterchange.ramps[rampIndex];
		const allCoordinates: [number, number][] = [];

		// Collect all coordinates from all paths in the ramp
		ramp.paths.forEach((path) => {
			path.nodes.forEach((node) => {
				allCoordinates.push([node.lat, node.lng]);
			});
		});

		if (allCoordinates.length > 0) {
			const bounds = L.latLngBounds(allCoordinates);
			map.fitBounds(bounds, { padding: [30, 30] });
		}
	}

	// Export the fitToRamp function so parent can access it
	export { fitToRamp };
</script>

<div bind:this={mapContainer} class="w-full h-full relative"></div>

<style>
	:global(.custom-interchange-marker) {
		background: transparent !important;
		border: none !important;
	}
</style>
