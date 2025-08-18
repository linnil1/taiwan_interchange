<script lang="ts">
	import Map from '$lib/components/Map.svelte';
	import InterchangeList from '$lib/components/InterchangeList.svelte';
	import InterchangeDetail from '$lib/components/InterchangeDetail.svelte';
	import { interchangesStore, fetchInterchanges } from '$lib/stores/interchanges.js';
	import type { Interchange } from '$lib/types.js';

	let selectedInterchange: Interchange | null = $state(null);
	let selectedRampIndex: number | null = $state(null);
	let searchTerm: string = $state('');
	let mapComponent: any = $state(null);

	// Fetch interchanges on mount
	$effect(() => {
		fetchInterchanges();
	});

	// Derive filtered interchanges from store and search term
	let filteredInterchanges = $derived(
		$interchangesStore && searchTerm !== undefined
			? $interchangesStore.filter(
					(interchange: Interchange) =>
						interchange.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
						String(interchange.id).includes(searchTerm)
				)
			: $interchangesStore || []
	);

	function selectInterchange(interchange: Interchange) {
		selectedInterchange = interchange;
		selectedRampIndex = null; // Reset ramp selection when changing interchange
		// Update current index
	}

	function clearSelection() {
		selectedInterchange = null;
		selectedRampIndex = null;
	}

	function handleFitToRamp(rampIndex: number) {
		if (mapComponent && mapComponent.fitToRamp) {
			mapComponent.fitToRamp(rampIndex);
		}
	}
</script>

<svelte:head>
	<title>Taiwan Interchange Explorer</title>
	<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
</svelte:head>

<div class="flex h-screen font-sans">
	<!-- Left Sidebar - Interchange List component -->
	<div class="w-80 flex flex-col bg-white border-r border-gray-300">
		<InterchangeList
			interchanges={filteredInterchanges}
			bind:searchTerm
			{selectedInterchange}
			onSelectInterchange={selectInterchange}
		/>
	</div>

	<!-- Detail Sidebar (appears when item selected) -->
	{#if selectedInterchange}
		<InterchangeDetail
			interchange={selectedInterchange}
			onClose={clearSelection}
			bind:selectedRampIndex
			onFitToRamp={handleFitToRamp}
		/>
	{/if}

	<!-- Map Container -->
	<div class="flex-1 relative">
		<Map
			bind:this={mapComponent}
			bind:selectedInterchange
			bind:selectedRampIndex
			interchanges={filteredInterchanges}
			onInterchangeSelect={selectInterchange}
		/>
	</div>
</div>
