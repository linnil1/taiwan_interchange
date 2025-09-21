import { writable } from 'svelte/store';
import type { InterchangeList } from '$lib/types.js';
import { isInterchange } from '$lib/types.js';

export const interchangesStore = writable<InterchangeList>([]);

export async function fetchInterchanges(): Promise<InterchangeList> {
	try {
		// Always fetch from static asset - works in both dev and production
		const response = await fetch('/interchanges.json');

		if (!response.ok) {
			throw new Error(`HTTP error! status: ${response.status}`);
		}

		const data = await response.json();

		// Validate data structure using type guards
		if (Array.isArray(data)) {
			// Validate each interchange
			const validatedData: InterchangeList = data.filter((item: unknown) => {
				if (!isInterchange(item)) {
					console.warn('Invalid interchange data:', item);
					return false;
				}
				return true;
			});

			interchangesStore.set(validatedData);
			console.log(`Loaded ${validatedData.length} interchanges`);
			return validatedData;
		} else {
			console.error('Invalid data format: expected array of interchanges');
			interchangesStore.set([]);
			return [];
		}
	} catch (error) {
		console.error('Failed to fetch interchanges:', error);
		interchangesStore.set([]);
		return [];
	}
}
