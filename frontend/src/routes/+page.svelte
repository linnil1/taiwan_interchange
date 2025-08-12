<script lang="ts">
	import Map from '$lib/components/Map.svelte';
	import InterchangeDetail from '$lib/components/InterchangeDetail.svelte';
	import { interchangesStore, fetchInterchanges } from '$lib/stores/interchanges.js';
	import type { Interchange } from '$lib/types.js';

	let selectedInterchange: Interchange | null = $state(null);
	let selectedRampIndex: number | null = $state(null);
	let searchTerm: string = $state('');

	// Fetch interchanges on mount
	$effect(() => {
		fetchInterchanges();
	});

	// Derive filtered interchanges from store and search term
	let filteredInterchanges = $derived(
		$interchangesStore && searchTerm !== undefined
			? $interchangesStore.filter((interchange: Interchange) =>
					interchange.name.toLowerCase().includes(searchTerm.toLowerCase())
				)
			: []
	);

	function selectInterchange(interchange: Interchange) {
		selectedInterchange = interchange;
		selectedRampIndex = null; // Reset ramp selection when changing interchange
	}

	function clearSelection() {
		selectedInterchange = null;
		selectedRampIndex = null;
	}
</script>

<svelte:head>
	<title>Taiwan Interchange Explorer</title>
	<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
</svelte:head>

<div class="flex h-screen font-sans">
	<!-- Left Sidebar - Compact List -->
	<div class="w-80 flex flex-col bg-white border-r border-gray-300">
		<!-- Search Controls -->
		<div class="p-3 border-b border-gray-300">
			<input
				type="text"
				placeholder="Search interchanges..."
				bind:value={searchTerm}
				class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
			/>
		</div>

		<!-- Compact Interchange List -->
		<div class="flex-1 overflow-y-auto">
			<div class="p-2">
				<div class="text-xs text-gray-500 mb-2">
					{filteredInterchanges.length} interchanges
				</div>
				{#each filteredInterchanges as interchange}
					<button
						class="w-full text-left p-3 mb-1 rounded border-l-4 transition-colors {selectedInterchange?.id ===
						interchange.id
							? 'bg-blue-50 border-blue-500'
							: 'bg-white border-transparent hover:bg-gray-50'}"
						onclick={() => selectInterchange(interchange)}
					>
						<div class="font-medium text-sm text-gray-800 truncate">
							{interchange.name}
						</div>
						<div class="text-xs text-gray-500 mt-1">
							{interchange.ramps.length} ramps
						</div>
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Detail Sidebar (appears when item selected) -->
	{#if selectedInterchange}
		<InterchangeDetail
			interchange={selectedInterchange}
			onClose={clearSelection}
			bind:selectedRampIndex
		/>
	{/if}

	<!-- Map Container -->
	<div class="flex-1 relative">
		<Map
			bind:selectedInterchange
			bind:selectedRampIndex
			interchanges={filteredInterchanges}
			onInterchangeSelect={selectInterchange}
		/>
	</div>
</div>
