// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		interface Platform {
			env: Env;
			cf: CfProperties;
			ctx: ExecutionContext;
		}

		// eslint-disable-next-line @typescript-eslint/no-empty-object-type
		interface Env {
			// Add environment variables here if needed
		}
	}
}

export {};
