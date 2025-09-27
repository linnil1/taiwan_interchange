<script lang="ts">
	import Map from '$lib/components/Map.svelte';
	import InterchangeList from '$lib/components/InterchangeList.svelte';
	import InterchangeDetail from '$lib/components/InterchangeDetail.svelte';
	import SearchComponent from '$lib/components/SearchComponent.svelte';
	import ProjectFooter from '$lib/components/ProjectFooter.svelte';
	import DraggableImageViewer from '$lib/components/DraggableImageViewer.svelte';
	import { interchangesStore, fetchInterchanges } from '$lib/stores/interchanges.js';
	import type { Interchange } from '$lib/types.js';
	import { onMount } from 'svelte';
	import * as m from '$lib/paraglide/messages';

	let selectedInterchange: Interchange | null = $state(null);
	let selectedRampIndex: number | null = $state(null);
	let searchTerm: string = $state('');
	let fitRampIndex: number | null = $state(null);
	let filteredInterchanges: Interchange[] = $state([]);
	let selectedImage: { src: string; alt: string } | null = $state(null);
	let showSidebar: boolean = $state(true); // Toggle for sidebar visibility

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
		showSidebar = true; // Show sidebar when closing detail view
	}
</script>

<svelte:head>
	<title>{m.project_title()}</title>
	<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
</svelte:head>

<div class="flex h-screen font-sans">
	<!-- Left Sidebar - Search and Interchange List components -->
	<div class="w-64 flex flex-col bg-white border-r border-gray-300" class:hidden={!showSidebar}>
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
		<!-- Project Footer -->
		<ProjectFooter />
	</div>

	<!-- Detail Sidebar (appears when item selected) -->
	{#if selectedInterchange}
		<InterchangeDetail
			interchange={selectedInterchange}
			onClose={clearSelection}
			bind:selectedRampIndex
			bind:fitRampIndex
			bind:selectedImage
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

<!-- Draggable Image Viewer -->
{#if selectedImage}
	<DraggableImageViewer bind:selectedImage />
{/if}
