<script lang="ts">
	import Map from '$lib/components/Map.svelte';
	import InterchangeList from '$lib/components/InterchangeList.svelte';
	import InterchangeDetail from '$lib/components/InterchangeDetail.svelte';
	import SearchComponent from '$lib/components/SearchComponent.svelte';
	import { interchangesStore, fetchInterchanges } from '$lib/stores/interchanges.js';
	import type { Interchange } from '$lib/types.js';
	import { Info } from 'lucide-svelte';
	import { onMount } from 'svelte';

	let selectedInterchange: Interchange | null = $state(null);
	let selectedRampIndex: number | null = $state(null);
	let searchTerm: string = $state('');
	let fitRampIndex: number | null = $state(null);
	let filteredInterchanges: Interchange[] = $state([]);

	// Fetch interchanges on mount
	onMount(fetchInterchanges);

	function selectInterchange(interchange: Interchange) {
		selectedInterchange = interchange;
		selectedRampIndex = null; // Reset ramp selection when changing interchange
		fitRampIndex = null; // Reset fit ramp index when changing interchange
	}

	function clearSelection() {
		selectedInterchange = null;
		selectedRampIndex = null;
		fitRampIndex = null;
	}
</script>

<svelte:head>
	<title>Taiwan Interchange Explorer</title>
	<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
</svelte:head>

<div class="flex h-screen font-sans">
	<!-- Left Sidebar - Search and Interchange List components -->
	<div class="w-72 flex flex-col bg-white border-r border-gray-300">
		<SearchComponent
			interchanges={$interchangesStore || []}
			bind:searchTerm
			bind:filteredInterchanges
		/>
		<div class="flex-1 overflow-hidden">
			<InterchangeList
				interchanges={filteredInterchanges}
				{selectedInterchange}
				onSelectInterchange={selectInterchange}
			/>
		</div>
		<!-- Project Info Footer -->
		<div class="border-t border-gray-300 px-3 py-2 bg-gray-50">
			<div class="flex items-center justify-between text-xs">
				<div>
					<span class="font-semibold text-gray-800">Taiwan Interchange Explorer</span>
					<span class="text-gray-600 ml-1">by <strong>linnil1</strong></span>
				</div>
				<a
					href="/about"
					class="px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors flex items-center gap-1"
				>
					<Info size={14} />
					About
				</a>
			</div>
		</div>
	</div>

	<!-- Detail Sidebar (appears when item selected) -->
	{#if selectedInterchange}
		<InterchangeDetail
			interchange={selectedInterchange}
			onClose={clearSelection}
			bind:selectedRampIndex
			bind:fitRampIndex
		/>
	{/if}

	<!-- Map Container -->
	<div class="flex-1 relative">
		<Map
			bind:selectedInterchange
			bind:selectedRampIndex
			bind:fitRampIndex
			interchanges={filteredInterchanges}
			onInterchangeSelect={selectInterchange}
		/>
	</div>
</div>
