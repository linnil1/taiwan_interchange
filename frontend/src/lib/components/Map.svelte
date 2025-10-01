<script lang="ts">
	import { browser } from '$app/environment';
	import { env } from '$env/dynamic/public';
	import type { Interchange } from '$lib/types.js';
	import type { Map as LeafletMap, Marker, Polyline, Layer } from 'leaflet';
	import { onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import * as m from '$lib/paraglide/messages';
	import { SiOpenstreetmap, SiGooglemaps } from '@icons-pack/svelte-simple-icons';

	let {
		selectedInterchange = $bindable(null),
		interchanges = [],
		onInterchangeSelect,
		selectedRampIndex = $bindable(null),
		fitRampIndex = $bindable(null)
	}: {
		selectedInterchange: Interchange | null;
		interchanges: Interchange[];
		onInterchangeSelect?: (interchange: Interchange) => void;
		selectedRampIndex?: number | null;
		fitRampIndex?: number | null;
	} = $props();

	let map: LeafletMap;
	let mapContainer: HTMLDivElement;
	let markerMap = new SvelteMap<number, Marker>(); // Track markers by interchange ID (number)
	let textWidthCache = new SvelteMap<string, number>(); // Cache text width measurements
	let selectedPaths: Polyline[] = [];
	let previousSelectedId: number | null = null; // Track previous selection
	let L: typeof import('leaflet') | null = null; // Leaflet will be loaded dynamically
	let currentMapLayer: Layer | null = null; // Track current base layer
	let selectedMapType = $state<'openstreetmap' | 'google'>('openstreetmap'); // Map type selection
	let availableMapTypes = $state<('openstreetmap' | 'google')[]>(['openstreetmap']); // Available map types
	let showMapTypeDropdown = $state(false); // Dropdown state
	let googleMapsAvailable = $state(false); // Track if Google Maps is available

	onMount(() => {
		// Initialize map asynchronously
		(async () => {
			if (browser && mapContainer) {
				// Check if Google Maps API key is available
				const apiKey = env.PUBLIC_GOOGLE_MAPS_API_KEY;
				googleMapsAvailable = !!(apiKey && apiKey.trim() !== '');

				// Dynamically import Leaflet in the browser
				const leafletModule = await import('leaflet');
				L = leafletModule.default;

				// Initialize the map
				map = L.map(mapContainer).setView([23.2, 120.3], 8);

				// Load Google Maps API if available
				if (googleMapsAvailable && apiKey) {
					await loadGoogleMapsAPI(apiKey);
				}
				try {
					await import('leaflet.gridlayer.googlemutant');
				} catch (e) {
					console.error('Failed to load leaflet.gridlayer.googlemutant', e);
					googleMapsAvailable = false;
				}

				// Set available map types
				availableMapTypes = googleMapsAvailable ? ['openstreetmap', 'google'] : ['openstreetmap'];

				// Add initial layer (OpenStreetMap)
				addMapLayer('openstreetmap');
			}
		})();
	});

	async function loadGoogleMapsAPI(apiKey: string) {
		return new Promise<void>((resolve) => {
			// Check if Google Maps API is already loaded
			if (window.google && window.google.maps) {
				resolve();
				return;
			}

			// Create and load the script
			const script = document.createElement('script');
			script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}`;
			script.async = true;
			script.defer = true;
			script.onload = () => resolve();
			script.onerror = () => {
				console.error('Failed to load Google Maps API');
				googleMapsAvailable = false;
				resolve();
			};
			document.head.appendChild(script);
		});
	}

	async function addMapLayer(mapType: 'openstreetmap' | 'google') {
		if (!map || !L) return;

		// Remove existing layer
		if (currentMapLayer) {
			map.removeLayer(currentMapLayer);
			currentMapLayer = null;
		}

		if (mapType === 'google' && availableMapTypes.includes('google')) {
			// Add Google Maps layer using GoogleMutant
			// @ts-expect-error: Not used, but import is necessary
			currentMapLayer = L.gridLayer
				.googleMutant({
					type: 'roadmap'
				})
				.addTo(map);
		} else {
			// Add OpenStreetMap layer
			currentMapLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
				maxZoom: 19
			}).addTo(map);
		}
	}

	function selectMapType(mapType: 'openstreetmap' | 'google') {
		selectedMapType = mapType;
		showMapTypeDropdown = false;
		addMapLayer(mapType);
	}

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

	// Fit to ramp when fitRampIndex changes
	$effect(() => {
		if (fitRampIndex !== null) {
			console.log('Fit ramp index updated', fitRampIndex);
			setTimeout(() => {
				fitToRamp(fitRampIndex as number);
				// Reset fitRampIndex after fitting
				fitRampIndex = null;
			}, 0);
		}
	});

	function clearSelectedPaths() {
		selectedPaths.forEach((path) => {
			map.removeLayer(path);
		});
		selectedPaths = [];
	}

	function clearAllMarkers() {
		markerMap.forEach((marker) => {
			map.removeLayer(marker);
		});
		markerMap.clear();
		// Don't clear textWidthCache - keep for reuse
	}

	function clearSpecificMarker(interchangeId: number) {
		const marker = markerMap.get(interchangeId);
		if (marker) {
			map.removeLayer(marker);
			markerMap.delete(interchangeId);
		}
	}

	function createSpecificMarker(interchange: Interchange) {
		if (!map || !L) return;

		// Remove existing marker if it exists
		clearSpecificMarker(interchange.id);

		const centerLat = (interchange.bounds.min_lat + interchange.bounds.max_lat) / 2;
		const centerLng = (interchange.bounds.min_lng + interchange.bounds.max_lng) / 2;

		const isSelected = selectedInterchange?.id === interchange.id;

		// Truncate interchange name to max 7 characters (for Chinese) with ... if exceeded
		const truncatedName =
			interchange.name.length > 7 ? interchange.name.slice(0, 7) + '...' : interchange.name;

		// Get or calculate text width (cache for performance)
		let textWidth = textWidthCache.get(truncatedName);
		if (!textWidth) {
			const tempDiv = document.createElement('div');
			tempDiv.className = 'interchange-marker-measure'; // Use CSS class
			tempDiv.style.position = 'absolute';
			tempDiv.style.visibility = 'hidden';
			tempDiv.textContent = truncatedName;
			document.body.appendChild(tempDiv);
			textWidth = tempDiv.offsetWidth;
			document.body.removeChild(tempDiv);
			textWidthCache.set(truncatedName, textWidth);
		}

		// Set minimum width with reduced padding
		const iconWidth = Math.max(textWidth + 4, 48);
		const iconHeight = 28;

		const marker = L.marker([centerLat, centerLng], {
			icon: L.divIcon({
				html: `<div class="interchange-marker ${isSelected ? 'selected' : ''}">${truncatedName}</div>`,
				className: 'custom-interchange-marker',
				iconSize: [iconWidth, iconHeight],
				iconAnchor: [iconWidth / 2, iconHeight / 2]
			})
		}).addTo(map);

		// Add click handler to marker
		marker.on('click', () => {
			if (onInterchangeSelect) {
				onInterchangeSelect(interchange);
			}
		});

		// Add hover effects
		const markerElement = marker.getElement();
		if (markerElement) {
			markerElement.addEventListener('mouseenter', () => {
				const div = markerElement.querySelector('div');
				if (div) {
					div.classList.add('hovered');
				}
			});

			markerElement.addEventListener('mouseleave', () => {
				const div = markerElement.querySelector('div');
				if (div) {
					div.classList.remove('hovered');
				}
			});
		}

		markerMap.set(interchange.id, marker);

		return marker;
	}

	function updateAllMarkers() {
		if (!map || !L) return;

		clearAllMarkers();

		// Show markers for all interchanges using the new createSpecificMarker function
		interchanges.forEach((interchange) => {
			createSpecificMarker(interchange);
		});

		// Fit map to show all markers if there are any
		if (markerMap.size > 0) {
			const markers = Array.from(markerMap.values());
			const group = new L.featureGroup(markers);
			map.fitBounds(group.getBounds(), { padding: [20, 20] });
		}
	}

	function updateMarkerColor(interchangeId: number) {
		const interchange = interchanges.find((i) => i.id === interchangeId);
		if (interchange) {
			createSpecificMarker(interchange); // This will recreate the marker with updated styling
		}
	}

	function updateSelectedInterchange(autoFocuse = true) {
		if (!map || !L) return;

		// Clear previous selected paths
		clearSelectedPaths();

		// Only update markers that actually changed
		const currentSelectedId = selectedInterchange?.id || null;

		// Update previously selected marker (if any) to unselected state
		if (previousSelectedId !== null && previousSelectedId !== currentSelectedId) {
			updateMarkerColor(previousSelectedId);
		}

		// Update currently selected marker (if any) to selected state
		if (currentSelectedId !== null) {
			updateMarkerColor(currentSelectedId);
		}

		// Update the previous selection tracking
		previousSelectedId = currentSelectedId;

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
</script>

<div class="w-full h-full relative">
	<div bind:this={mapContainer} class="w-full h-full"></div>

	<!-- Map Type Selector -->
	{#if availableMapTypes.length > 1}
		<div
			class="absolute top-2.5 right-2.5 z-[1000]"
			role="button"
			tabindex="0"
			onmouseenter={() => (showMapTypeDropdown = true)}
			onmouseleave={() => (showMapTypeDropdown = false)}
		>
			<div
				class="flex items-center gap-2 px-3 py-1.5 bg-white border-2 border-gray-300/70 rounded text-sm font-medium text-gray-700 shadow-md hover:bg-gray-50 transition-colors cursor-pointer"
			>
				{#if selectedMapType === 'google'}
					<SiGooglemaps size={16} />
					<span>{m.map_type_google()}</span>
				{:else}
					<SiOpenstreetmap size={16} />
					<span>{m.map_type_openstreetmap()}</span>
				{/if}
				<svg class="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"
					></path>
				</svg>
			</div>

			{#if showMapTypeDropdown}
				<div
					class="absolute top-full right-0 bg-white border-2 border-gray-300/70 rounded shadow-lg overflow-hidden w-full"
				>
					{#each availableMapTypes as mapType (mapType)}
						<button
							onclick={() => selectMapType(mapType)}
							class="w-full px-3 py-2 flex items-center gap-2 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors {selectedMapType ===
							mapType
								? 'text-blue-600'
								: ''}"
						>
							{#if mapType === 'google'}
								<SiGooglemaps size={16} />
								<span>{m.map_type_google()}</span>
							{:else}
								<SiOpenstreetmap size={16} />
								<span>{m.map_type_openstreetmap()}</span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	:global(.custom-interchange-marker) {
		/* Ensure no default styles from Leaflet */
		background: none !important;
		border: none !important;
	}

	/* For measuring text width - uses same styling as actual marker */
	:global(.interchange-marker-measure) {
		font-size: 0.75rem;
		font-weight: 500;
		padding: 3px 6px;
		white-space: nowrap;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	}

	:global(.interchange-marker) {
		/* Transparent clickable container - keeps full click area */
		background: transparent;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 100%;
		height: 100%;
		cursor: pointer;
		font-size: 0.75rem;
		font-weight: 500;
		white-space: nowrap;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
		transition: all 0.2s ease-out;

		/* Text gets background color around it */
		color: white;
		text-shadow: 0 0 4px rgba(0, 0, 0, 0.8); /* Fallback for readability */
		position: relative;
	}

	:global(.interchange-marker::before) {
		/* Background only around the text content */
		content: '';
		position: absolute;
		background-color: rgba(55, 65, 81, 0.9);
		border-radius: 0.5rem;
		padding: 3px 6px;
		inset: 6px 4px; /* Tight around text */
		z-index: -1;
	}

	:global(.interchange-marker.selected::before) {
		background-color: rgba(37, 99, 235, 0.9);
		box-shadow: 0 2px 6px rgba(37, 99, 235, 0.4);
	}

	:global(.interchange-marker.hovered) {
		transform: scale(1.05);
	}

	:global(.interchange-marker.hovered::before) {
		background-color: rgba(55, 65, 81, 1); /* Solid on hover */
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.4);
	}

	:global(.interchange-marker.selected.hovered::before) {
		background-color: rgba(37, 99, 235, 1);
		box-shadow: 0 4px 8px rgba(37, 99, 235, 0.5);
	}
</style>
