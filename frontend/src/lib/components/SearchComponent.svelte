<script lang="ts">
	import type { Interchange } from '$lib/types.js';
	import { Filter } from 'lucide-svelte';
	import * as m from '$lib/paraglide/messages';

	let {
		interchanges = [],
		searchTerm = $bindable(''),
		filteredInterchanges = $bindable([])
	} = $props<{
		interchanges: Interchange[];
		searchTerm: string;
		filteredInterchanges: Interchange[];
	}>();

	let includeWeighStations = $state(true);
	let includeServiceAreas = $state(true);
	let selectedRefFilter = $state('all');
	let showFilters = $state(false);

	// Get unique refs from all interchanges
	let availableRefs = $derived(
		Array.from(
			new Set(
				interchanges.flatMap((interchange: Interchange) => interchange.refs.map((ref) => ref.name))
			)
		).sort()
	);

	// Filter interchanges based on search criteria
	$effect(() => {
		if (!interchanges) {
			filteredInterchanges = [];
			return;
		}

		let filtered = interchanges.filter((interchange: Interchange) => {
			// Text search filter (removed ID search)
			const matchesSearch =
				searchTerm === '' || interchange.name.toLowerCase().includes(searchTerm.toLowerCase());

			// 地磅站 filter
			const matchesWeighStation =
				includeWeighStations ||
				!(interchange.name.includes('地磅站') && !interchange.name.includes(';'));

			// 服務區/休息站 filter
			const matchesServiceArea =
				includeServiceAreas ||
				!(
					(interchange.name.includes('服務區') || interchange.name.includes('休息站')) &&
					!interchange.name.includes(';')
				);

			// Refs filter
			const matchesRefFilter =
				selectedRefFilter === 'all' ||
				interchange.refs.some((ref) => ref.name === selectedRefFilter);

			return matchesSearch && matchesWeighStation && matchesServiceArea && matchesRefFilter;
		});

		filteredInterchanges = filtered;
	});
</script>

<div class="bg-gray-100 p-3 border-b border-gray-300 sticky top-0">
	<!-- Title -->
	<div class="font-bold mb-2">
		{!includeWeighStations ||
		!includeServiceAreas ||
		selectedRefFilter !== 'all' ||
		searchTerm.trim() !== ''
			? `${m.interchanges()} (${filteredInterchanges.length}/${interchanges.length})`
			: `${m.interchanges()} (${interchanges.length})`}
	</div>

	<!-- Search input with filter button -->
	<div class="flex gap-2 w-full">
		<input
			class="flex-1 rounded border border-gray-300 text-sm px-2 py-1 min-w-24 focus:outline-none focus:ring-2 focus:ring-blue-400"
			type="search"
			placeholder={m.search_placeholder()}
			bind:value={searchTerm}
			aria-label={m.search_placeholder()}
		/>
		<button
			onclick={() => (showFilters = !showFilters)}
			class="px-2 py-1 rounded transition-colors flex items-center justify-center {showFilters
				? 'bg-blue-600 text-white hover:bg-blue-700'
				: 'text-blue-600 hover:text-blue-800 hover:bg-blue-50'}"
			title={m.filters()}
		>
			<Filter size={16} />
		</button>
	</div>

	<!-- Filter options (collapsible) -->
	{#if showFilters}
		<div class="space-y-2 mt-2">
			<!-- 地磅站 checkbox -->
			<label class="flex items-center text-sm text-gray-700">
				<input
					type="checkbox"
					bind:checked={includeWeighStations}
					class="mr-2 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
				/>
				{m.include_weigh_stations()}
			</label>

			<!-- 服務區/休息站 checkbox -->
			<label class="flex items-center text-sm text-gray-700">
				<input
					type="checkbox"
					bind:checked={includeServiceAreas}
					class="mr-2 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
				/>
				{m.include_service_areas()}
			</label>

			<!-- Refs filter dropdown -->
			<div class="flex items-center text-sm text-gray-700 mr-2">
				<label for="ref-filter" class="mr-2 flex-shrink-0">{m.route()}</label>
				<select
					id="ref-filter"
					bind:value={selectedRefFilter}
					class="flex-1 w-full rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
				>
					<option value="all">{m.all_routes()}</option>
					{#each availableRefs as ref (ref)}
						<option value={ref}>{ref}</option>
					{/each}
				</select>
			</div>
		</div>
	{/if}
</div>
