<script lang="ts">
	import type { Interchange } from '$lib/types.js';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
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
			// Text search filter
			const matchesSearch =
				searchTerm === '' ||
				interchange.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
				String(interchange.id).includes(searchTerm);

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
	<div class="flex justify-between items-center mb-2">
		<div class="font-bold">
			{!includeWeighStations || !includeServiceAreas || selectedRefFilter !== 'all'
				? m.interchanges_filtered({ count: filteredInterchanges.length })
				: m.interchanges_total({ count: interchanges.length })}
		</div>
		<button
			onclick={() => (showFilters = !showFilters)}
			class="text-sm text-blue-600 hover:text-blue-800 transition-colors flex items-center gap-1"
			title="Toggle filter options"
		>
			{#if showFilters}
				<ChevronUp size={16} />
			{:else}
				<ChevronDown size={16} />
			{/if}
			{m.filters()}
		</button>
	</div>

	<!-- Search input -->
	<input
		class="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 mb-3"
		type="search"
		placeholder={m.search_placeholder()}
		bind:value={searchTerm}
	/>

	<!-- Filter options (collapsible) -->
	{#if showFilters}
		<div class="space-y-2">
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
