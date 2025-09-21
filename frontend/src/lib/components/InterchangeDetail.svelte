<script lang="ts">
	import { X, ZoomIn } from 'lucide-svelte';
	import type { Interchange, Ramp, Destination } from '$lib/types.js';
	import * as m from '$lib/paraglide/messages';

	let {
		interchange,
		onClose,
		selectedRampIndex = $bindable(null),
		fitRampIndex = $bindable(null),
		selectedImage = $bindable(null)
	}: {
		interchange: Interchange;
		onClose: () => void;
		selectedRampIndex?: number | null;
		fitRampIndex?: number | null;
		selectedImage?: { src: string; alt: string } | null;
	} = $props();

	let rampElements: HTMLElement[] = [];

	// Scroll to selected ramp when selectedRampIndex changes
	$effect(() => {
		if (selectedRampIndex !== null && rampElements[selectedRampIndex]) {
			rampElements[selectedRampIndex].scrollIntoView({
				behavior: 'smooth',
				block: 'center'
			});
		}
	});

	function selectRamp(rampIndex: number) {
		selectedRampIndex = selectedRampIndex === rampIndex ? null : rampIndex;
	}

	function navigateToRamp(rampId: number) {
		const rampIndex = interchange.ramps.findIndex((r) => r.id === rampId);
		if (rampIndex !== -1) {
			selectedRampIndex = rampIndex;
		}
	}

	// Helper function to get ramp connections within this interchange
	function getRampConnections(ramp: Ramp) {
		const fromRamps = ramp.from_ramps
			.map((id: number) => interchange.ramps.find((r) => r.id === id))
			.filter((r: Ramp | undefined): r is Ramp => r !== undefined);

		const toRamps = ramp.to_ramps
			.map((id: number) => interchange.ramps.find((r) => r.id === id))
			.filter((r: Ramp | undefined): r is Ramp => r !== undefined);

		return { fromRamps, toRamps };
	}

	// Helper function to format ramp display name - just show #number
	function getRampDisplayName(ramp: Ramp) {
		return `#${ramp.id}`;
	}

	// Helper function to format ramp display name for navigation - show destinations + #number
	function getRampNavigationDisplayName(ramp: Ramp) {
		if (ramp.destination && ramp.destination.length > 0) {
			const destinationNames = ramp.destination.map((d: Destination) => d.name).join(', ');
			return `${destinationNames} #${ramp.id}`;
		}
		return `#${ramp.id}`;
	}

	// Helper function to get OSM link based on relation type
	function getOSMLink(id: number, relationType: string) {
		switch (relationType) {
			case 'RELATION':
				return `https://www.openstreetmap.org/relation/${id}`;
			case 'WAY':
				return `https://www.openstreetmap.org/way/${id}`;
			case 'NODE':
				return `https://www.openstreetmap.org/node/${id}`;
			default:
				return `https://www.openstreetmap.org/relation/${id}`;
		}
	}
</script>

<div class="w-86 bg-white border-r border-gray-300 overflow-y-auto">
	<div class="sticky top-0 bg-white border-b border-gray-300 p-4">
		<div class="flex justify-between items-start">
			<div class="min-w-0 flex-1">
				<h2 class="text-lg font-bold text-gray-800">{interchange.name}</h2>
				<div class="text-sm text-gray-600">
					{interchange.ramps.length === 1
						? m.ramp({ count: interchange.ramps.length })
						: m.ramps({ count: interchange.ramps.length })}
				</div>
			</div>
			<button
				class="px-3 py-1 bg-red-500 text-white text-sm rounded hover:bg-red-600 transition-colors flex-shrink-0 flex items-center gap-1"
				onclick={onClose}
			>
				<X size={16} />
			</button>
		</div>
	</div>

	<div class="p-4">
		<!-- Bounds Info -->
		<!--
		<div class="mb-4 p-3 bg-gray-50 rounded text-xs">
			<strong>Bounds:</strong>
			<br />
			Lat: {interchange.bounds.min_lat.toFixed(6)} to {interchange.bounds.max_lat.toFixed(6)}
			<br />
			Lng: {interchange.bounds.min_lng.toFixed(6)} to {interchange.bounds.max_lng.toFixed(6)}
		</div>
		-->
		<!-- Show refs if available -->
		{#if interchange.refs && interchange.refs.length > 0}
			<div class="mt-2">
				<div class="text-xs text-gray-500 mb-1">{m.connected_to()}</div>
				<div class="flex flex-wrap gap-1">
					{#each interchange.refs as ref (ref.id)}
						<span
							class="inline-flex items-center rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700 border border-blue-200"
						>
							<a
								href="https://www.openstreetmap.org/relation/{ref.id}"
								target="_blank"
								rel="noopener noreferrer"
								class="hover:underline"
							>
								{ref.name}
							</a>
						</span>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Wikipedia Data Section -->
		{#if interchange.wikis && interchange.wikis.length > 0}
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			{#each interchange.wikis as wikiData (wikiData.url)}
				<div class="mt-3 p-3 bg-blue-50 border border-blue-200 rounded w-full">
					<h3 class="text-sm font-semibold text-blue-800 mb-2">
						<a
							href={wikiData.url}
							target="_blank"
							rel="noopener noreferrer"
							class="hover:underline"
						>
							{m.wikipedia_data()}
						</a>
						{#if wikiData.interchange_url}
							<span class="text-blue-600"> - </span>
							<a
								href={wikiData.interchange_url}
								target="_blank"
								rel="noopener noreferrer"
								class="hover:underline text-blue-600"
							>
								{wikiData.name}
							</a>
						{/if}
					</h3>

					<div class="space-y-2 text-xs">
						{#if wikiData.exit_text}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_exit()}</span>
								<span class="text-gray-600 flex-1">{wikiData.exit_text}</span>
							</div>
						{/if}

						{#if wikiData.km_distance}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_distance()}</span
								>
								<span class="text-gray-600 flex-1">{wikiData.km_distance} km</span>
							</div>
						{/if}

						{#if wikiData.region}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_region()}</span>
								<span class="text-gray-600 flex-1">{wikiData.region}</span>
							</div>
						{/if}

						{#if wikiData.interchange_type && wikiData.interchange_type.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_type()}</span>
								<span class="text-gray-600 flex-1">{wikiData.interchange_type.join(', ')}</span>
							</div>
						{/if}

						{#if wikiData.opening_date && wikiData.opening_date.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_opened()}</span>
								<span class="text-gray-600 flex-1">{wikiData.opening_date.join(', ')}</span>
							</div>
						{/if}

						{#if wikiData.forward_direction && wikiData.forward_direction.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_forward()}</span>
								<span class="text-gray-600 flex-1">{wikiData.forward_direction.join(', ')}</span>
							</div>
						{/if}

						{#if wikiData.reverse_direction && wikiData.reverse_direction.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.wiki_reverse()}</span>
								<span class="text-gray-600 flex-1">{wikiData.reverse_direction.join(', ')}</span>
							</div>
						{/if}

						{#if wikiData.connecting_roads && wikiData.connecting_roads.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0"
									>{m.wiki_connecting_roads()}</span
								>
								<span class="text-gray-600 flex-1">{wikiData.connecting_roads.join(', ')}</span>
							</div>
						{/if}
					</div>
				</div>
			{/each}
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		{/if}

		<!-- Government Data Section -->
		{#if interchange.govs && interchange.govs.length > 0}
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			{#each interchange.govs as govData (govData.url)}
				{@const isInterchange = govData.facility_type && govData.facility_type.includes('交流道')}
				{@const borderColor = isInterchange ? 'border-red-200' : 'border-cyan-400'}
				{@const bgColor = isInterchange ? 'bg-red-50' : 'bg-cyan-50'}
				{@const textColor = isInterchange ? 'text-red-800' : 'text-cyan-800'}

				<div class="mt-3 p-3 {bgColor} border {borderColor} rounded w-full">
					<h3 class="text-sm font-semibold {textColor} mb-2">
						<a
							href={govData.url}
							target="_blank"
							rel="external noopener noreferrer"
							class="hover:underline"
						>
							{m.freeway_bureau_data()} - {govData.name}
						</a>
					</h3>

					{#if govData.interchange_url}
						<div class="mb-2">
							<button
								type="button"
								class="block w-full"
								onclick={() =>
									(selectedImage = {
										src: govData.interchange_url,
										alt: `${govData.name} diagram`
									})}
							>
								<img
									src={govData.interchange_url}
									alt="{govData.name} diagram"
									class="max-w-full h-auto rounded border cursor-pointer hover:shadow-lg transition-shadow"
									loading="lazy"
								/>
							</button>
						</div>
					{/if}

					<div class="space-y-2 text-xs">
						{#if govData.km_distance}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.gov_distance()}</span>
								<span class="text-gray-600 flex-1">{govData.km_distance} km</span>
							</div>
						{/if}

						{#if govData.facility_type}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0"
									>{m.gov_facility_type()}</span
								>
								<span class="text-gray-600 flex-1">{govData.facility_type}</span>
							</div>
						{/if}

						{#if govData.service_area && govData.service_area.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0"
									>{m.gov_service_area()}</span
								>
								<span class="text-gray-600 flex-1">{govData.service_area.join(', ')}</span>
							</div>
						{/if}

						{#if govData.southbound_exit && govData.southbound_exit.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0"
									>{m.gov_southbound()}</span
								>
								<span class="text-gray-600 flex-1">{govData.southbound_exit.join(', ')}</span>
							</div>
						{/if}

						{#if govData.northbound_exit && govData.northbound_exit.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0"
									>{m.gov_northbound()}</span
								>
								<span class="text-gray-600 flex-1">{govData.northbound_exit.join(', ')}</span>
							</div>
						{/if}

						{#if govData.eastbound_exit && govData.eastbound_exit.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.gov_eastbound()}</span
								>
								<span class="text-gray-600 flex-1">{govData.eastbound_exit.join(', ')}</span>
							</div>
						{/if}

						{#if govData.westbound_exit && govData.westbound_exit.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.gov_westbound()}</span
								>
								<span class="text-gray-600 flex-1">{govData.westbound_exit.join(', ')}</span>
							</div>
						{/if}

						{#if govData.notes && govData.notes.length > 0}
							<div class="flex">
								<span class="font-medium text-gray-700 w-16 flex-shrink-0">{m.gov_notes()}</span>
								<span class="text-gray-600 flex-1">{govData.notes.join(', ')}</span>
							</div>
						{/if}
					</div>
				</div>
			{/each}
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		{/if}

		<!-- Ramps List -->
		<div class="mt-8">
			{#each interchange.ramps as ramp, i (ramp.id)}
				<div
					bind:this={rampElements[i]}
					role="button"
					tabindex="0"
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							selectRamp(i);
						}
					}}
					onclick={() => selectRamp(i)}
					class="w-full mb-3 p-3 border rounded transition-all duration-300 cursor-pointer {selectedRampIndex ===
					i
						? 'border-blue-500 bg-blue-50 shadow-md'
						: 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'}"
				>
					<div class="flex justify-between items-start mb-2">
						<div class="flex-1 text-center">
							<div
								class="font-medium text-sm {selectedRampIndex === i
									? 'text-blue-700'
									: ''} flex items-center justify-center"
							>
								{getRampDisplayName(ramp)}
								{#if selectedRampIndex === i}
									<button
										type="button"
										class="ml-2 text-blue-500 hover:text-blue-700 transition-colors"
										onclick={(e) => {
											e.stopPropagation();
											fitRampIndex = i;
										}}
										title={m.zoom_to_ramp()}
									>
										<ZoomIn size={16} />
									</button>
								{/if}
							</div>
						</div>
						<span class="text-xs text-gray-500 flex-shrink-0">
							{ramp.paths.length === 1
								? m.path_single({ count: ramp.paths.length })
								: m.paths({ count: ramp.paths.length })}
						</span>
					</div>
					<!-- Destination information directly below ramp title - each destination on its own row, centered -->
					{#if ramp.destination && ramp.destination.length > 0}
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<div class="text-sm text-gray-600 mb-2 text-center">
							{#each ramp.destination as d (d.id)}
								<div class="flex items-center justify-center mb-1">
									<span
										class="px-1.5 py-0.5 rounded border text-[10px] mr-2 {d.destination_type ===
										'ENTER'
											? 'border-gray-400 text-gray-700 bg-gray-100'
											: 'border-gray-400 text-gray-700 bg-white'}">{d.destination_type}</span
									>
									<span class="mr-2 font-bold">{d.name}</span>
									<a
										href={getOSMLink(d.id, d.relation_type)}
										target="_blank"
										rel="noopener noreferrer"
										class="text-blue-600 hover:text-blue-800 underline text-xs"
										onclick={(e) => e.stopPropagation()}
									>
										{d.id}
									</a>
								</div>
							{/each}
						</div>
					{:else}
						<div class="text-sm text-gray-600 mb-2 text-center font-bold">{m.unknown()}</div>
					{/if}
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
					<!-- Ramp Navigation -->
					{#if getRampConnections(ramp).fromRamps.length > 0 || getRampConnections(ramp).toRamps.length > 0}
						{@const connections = getRampConnections(ramp)}
						<div class="mb-2 text-xs grid grid-cols-2 gap-2 mt-3 mx-2">
							<!-- Previous ramps (left column) -->
							<div class="flex flex-col gap-1">
								{#each connections.fromRamps as fromRamp (fromRamp.id)}
									<button
										type="button"
										class="w-full px-2 py-1 bg-green-500 text-white rounded hover:bg-green-600 transition-colors text-center leading-tight flex items-center justify-center"
										onclick={(e) => {
											e.stopPropagation();
											navigateToRamp(fromRamp.id);
										}}
									>
										← {getRampNavigationDisplayName(fromRamp)}
									</button>
								{/each}
							</div>
							<!-- Next ramps (right column) -->
							<div class="flex flex-col gap-1">
								{#each connections.toRamps as toRamp (toRamp.id)}
									<button
										type="button"
										class="w-full px-2 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors text-center leading-tight flex items-center justify-center"
										onclick={(e) => {
											e.stopPropagation();
											navigateToRamp(toRamp.id);
										}}
									>
										{getRampNavigationDisplayName(toRamp)} →
									</button>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Paths within ramp -->
					<div class="ml-2 mt-6">
						{#each ramp.paths as path, j (`${path.id}-${path.part}`)}
							<div class="mb-2 p-2 bg-gray-50 rounded text-xs">
								<div class="flex items-center justify-between mb-1">
									<div class="font-medium text-gray-700">
										{m.path({ number: j + 1 })}
										<a
											href="https://www.openstreetmap.org/way/{path.id}"
											target="_blank"
											rel="noopener noreferrer"
											class="text-blue-600 hover:text-blue-800 underline ml-2"
											onclick={(e) => e.stopPropagation()}
										>
											Way {path.id}
										</a>
										{#if path.part > 0}
											{m.part({ number: path.part })}
										{/if}
									</div>
									<div class="text-gray-600 text-xs">
										{m.nodes({ count: path.nodes.length })}
									</div>
								</div>

								<!-- Node IDs - Horizontal layout with left alignment -->
								<div class="text-gray-500 flex items-start">
									<span class="font-medium mr-2 flex-shrink-0">{m.nodes_label()}</span>
									<div
										class="max-h-16 overflow-y-auto text-xs leading-tight flex-1 flex flex-wrap items-start"
									>
										{#each path.nodes as node, k (node.id)}
											<a
												href="https://www.openstreetmap.org/node/{node.id}"
												target="_blank"
												rel="noopener noreferrer"
												class="inline-block mr-1 text-blue-600 hover:text-blue-800 underline"
												onclick={(e) => e.stopPropagation()}
											>
												{node.id}
											</a>{k < path.nodes.length - 1 ? ',' : ''}
										{/each}
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	</div>
</div>
