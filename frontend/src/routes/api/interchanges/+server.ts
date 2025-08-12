import { json } from '@sveltejs/kit';
import { dev } from '$app/environment';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ platform }) => {
	try {
		if (dev) {
			// Development: fetch from local Flask server
			const response = await fetch('http://localhost:5000/api/interchanges');

			if (!response.ok) {
				throw new Error(`Flask server error: ${response.status}`);
			}

			const data = await response.json();
			return json(data);
		} else {
			// Production: fetch from Cloudflare KV
			if (!platform?.env?.INTERCHANGES_KV) {
				throw new Error('Cloudflare KV binding not found');
			}

			const kvData = await platform.env.INTERCHANGES_KV.get('interchanges');

			if (!kvData) {
				throw new Error('No interchange data found in KV store');
			}

			const data = JSON.parse(kvData);
			return json(data);
		}
	} catch (error) {
		console.error('Error fetching interchanges:', error);

		// Return error response
		return json({ error: 'Failed to fetch interchange data' }, { status: 500 });
	}
};
