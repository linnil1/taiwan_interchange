<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		Target,
		Database,
		Lightbulb,
		Link,
		AlertTriangle,
		Map,
		Globe,
		Settings,
		Users,
		Zap,
		RefreshCw,
		Signal,
		Eye,
		AlertCircle,
		BookOpen,
		Sparkles
	} from 'lucide-svelte';
	import { SiGithub } from '@icons-pack/svelte-simple-icons';
	import * as m from '$lib/paraglide/messages';
	import { resolve } from '$app/paths';

	const challenges = [
		{
			en: 'Extract ramp data (including non-motorway_link tagged roads like endpoints)',
			zh: '抓取匝道資料（包含有些非標記 motorway_link 的道路，比如說端點）'
		},
		{
			en: 'Classify ramps to corresponding interchanges (some edge cases are hardcoded; some inseparable interchanges remain grouped)',
			zh: '將匝道分類到對應交流道（當然，有些奇怪的 case 還是寫死的；有些無法分開的交流道還是會弄在一起）'
		},
		{
			en: 'Interchange naming (mostly using junction names, but manual handling for special cases)',
			zh: '交流道命名（大部分使用出口節點名稱，但也要手動處理一些特殊案例）'
		},
		{
			en: 'Handle ramps for weigh stations or interchanges that only serve weigh stations',
			zh: '處理匝道可能用於地磅站，或該交流道只有地磅站的情況'
		},
		{
			en: 'Reorganize and merge nodes/ways (ways in OSM serve non-purely functional roles, so we use RAMP class as wrapper)',
			zh: '重新整理合併 node 和 way（尤其是 way 在 OSM 中的角色非純粹功能性，所以我用 RAMP 這個 class 來包裝）'
		},
		{
			en: 'Mark ramps and their upstream ramps with destination roads',
			zh: '標記匝道及其上游匝道的目標道路'
		},
		{
			en: 'Special handling for elevated roads in Xizhi, Yangmei, and Kaohsiung',
			zh: '汐止、楊梅的高架道路，高雄的高架道路有特別處理'
		},
		{
			en: 'Comprehensive handling of OSM tag markings (there are really many different tagging methods)',
			zh: '完整處理 OSM 裡的 tag 標記（標記方法真的很多種）'
		},
		{
			en: 'Build interactive map with complete OSM Way and Node ID references',
			zh: '建立互動地圖並有完整的 OSM Way 和 Node ID 參考'
		},
		{
			en: 'Handle ramp connection issues, including cloverleaf interchange loops; some ramps are not consistently tagged as one-way',
			zh: '處理匝道連接問題，包含苜蓿葉型交流道中的環路問題；而且有些匝道並未被標註為單向'
		},
		{
			en: 'Establish connections between ramps and national highways and sort accordingly',
			zh: '建立匝道與國道的連結並以此排序'
		},
		{
			en: 'Integrate both OpenStreetMap and Google Maps in the frontend for flexible visualization',
			zh: '在前端整合開放街圖和 Google 地圖，提供彈性的視覺化選擇'
		},
		{
			en: 'Integrate Wikipedia interchange data (parse structured pages to enrich junction names, descriptions, and listings)',
			zh: '結合維基百科交流道資料（解析結構化頁面以補強交流道名稱、描述與列表）'
		},
		{
			en: 'Extract Wikidata identifiers/links from OSM tags',
			zh: '擷取 OSM tags 的 Wikidata ID/連結'
		},
		{
			en: 'Integrate Freeway Bureau textual and facility data (metadata, facility lists) to enrich junction information with official descriptions and attributes',
			zh: '整合交通部高速公路局的文字與設施資料，以官方描述與屬性補強交流道資訊'
		},
		{
			en: 'Support official interchange sketch images: convert provided PDFs to web-friendly images or tiles and display them with an interactive viewer (pan/zoom, overlay layers, toggle annotations)',
			zh: '支援官方交流道示意圖：若為 PDF 先轉成網頁友好圖片或切片，並在網站上顯示，提供互動檢視（平移/縮放、圖層疊加、開關標註）'
		}
	];
</script>

<svelte:head>
	<title>{m.about()} - {m.project_title()}</title>
</svelte:head>

<div class="min-h-screen bg-gray-50 py-8">
	<div class="max-w-4xl mx-auto px-6">
		<!-- Floating Back Buton -->
		<div class="fixed bottom-6 left-6 z-50">
			<button
				onclick={() => goto(resolve('/'))}
				class="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center shadow-lg"
			>
				{m.back_to_explorer()}
			</button>
		</div>
		<!-- Header -->
		<div class="mb-8 relative">
			<div class="flex items-center gap-4 mb-3">
				<img
					src="/favicon-192x192.png"
					alt="Taiwan Interchange Explorer Logo"
					class="w-16 h-16 rounded-lg shadow-sm"
				/>
				<h1 class="text-4xl font-bold text-gray-900">Taiwan Interchange Explorer</h1>
			</div>
			<p class="text-xl text-gray-600 mb-4">台灣交流道整理與視覺化</p>
			<p class="text-lg text-gray-700 max-w-3xl mb-3">
				This website provides comprehensive organization of all Taiwan interchanges with detailed
				ramp-level annotations, partially verified by manual correction, offering classification,
				visualization, and search capabilities.
			</p>
			<p class="text-gray-600 text-sm max-w-3xl">
				這個網頁整理了所有台灣交流道，並有精細到匝道等級的標記，且部分由人工校正，並提供分類、視覺化、查詢功能，大部分資料來自於
				OSM。
			</p>
		</div>

		<!-- Content -->
		<div class="space-y-8 mb-8">
			<!-- Project Vision -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<Target class="w-6 h-6 text-blue-600" />
					Project Vision / 專案願景
				</h2>

				<div class="space-y-6">
					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Eye class="w-5 h-5 text-blue-600" />
							Visualizing Highway Interchanges / 交流道視覺化
						</h3>
						<p class="text-gray-700 mb-3">
							Creating a comprehensive visualization of highway interchanges sounds straightforward,
							but requires consideration of numerous complex aspects. For example: determining ramp
							sources and directions, how to programmatically read and process so many interchanges,
							dealing with circular path issues in cloverleaf interchanges, and managing internal
							inconsistencies within OSM itself.
						</p>
						<p class="text-gray-600 text-sm">
							建立完整的交流道視覺化聽起來很簡單，但要考慮的方向非常多，比如說怎麼知道匝道的來源與方向、如何程式化的讀取這麼多交流道、苜蓿葉型交流道會有循環問題，甚至可能OSM(開放街圖)內部也會不一致。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<AlertCircle class="w-5 h-5 text-amber-600" />
							Current Resources Limitations / 現有資源限制
						</h3>
						<p class="text-gray-700 mb-3">
							Currently, the clearest public resources are the Taiwan Freeway Bureau's textual
							descriptions and simplified diagrams (<a
								href="https://www.freeway.gov.tw/Publish.aspx?cnid=1906"
								target="_blank"
								rel="noopener"
								class="text-blue-600 hover:text-blue-800 underline">freeway.gov.tw</a
							>), but these cannot be directly mapped to Google Maps, OSM, or other mapping
							platforms. There is also a Wikipedia list page (<a
								href="https://zh.wikipedia.org/zh-tw/%E4%B8%AD%E5%B1%B1%E9%AB%98%E9%80%9F%E5%85%AC%E8%B7%AF%E4%BA%A4%E6%B5%81%E9%81%93%E5%88%97%E8%A1%A8"
								target="_blank"
								rel="noopener"
								class="text-blue-600 hover:text-blue-800 underline">Wikipedia</a
							>), but it is mostly plain text and lacks direct geospatial mapping information.
						</p>
						<p class="text-gray-600 text-sm">
							目前可取得較清楚的資源是台灣高工局的文字說明與簡化示意圖（連結如上），但無法直接對應到
							Google Map、OSM 或其他圖資平台。 Wikipedia
							上有相關列表，但多為純文字，缺乏可直接用的地理資訊。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<BookOpen class="w-5 h-5 text-green-600" />
							Detailed Vision & Goals / 詳細願景與目標
						</h3>
						<p class="text-gray-700 mb-3">
							I aim to identify all interchange-related roads, classify them, correctly annotate
							each classification with proper interchange names, and mark every ramp with precise
							sources and destinations. This includes organizing each highway, the roads they
							connect to, and the intermediate ramps (sometimes still classified as highways in
							OSM). After organizing this data, we'll build a website so people can use it directly
							— search, interact, and explore interchanges. This makes the data more than just a
							JSON dump: it becomes a searchable, interactive resource accessible via a user
							interface.
						</p>
						<p class="text-gray-600 text-sm">
							我希望能找出所有交流道相關的道路，並分類，標註該分類正確的交流道名稱，並標註到每個匝道，顯示精確的來源和目的地。這包括了要整理出每條高速公路與每條高速公路所連接的道路與中間的匝道（有時在
							OSM
							還是以高速公路類別）。整理後，我們會做個網頁讓大家可以直接使用，甚至可以查詢與互動，讓這些資料不只是以
							JSON 格式分享，而是能透過介面被查詢與探索。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Sparkles class="w-5 h-5 text-purple-600" />
							Enabling Applications / 支援應用
						</h3>
						<p class="text-gray-700">
							With this level of detail, various applications become possible. Rather than listing
							them all, from an ordinary person's perspective, being able to appreciate the
							beautiful layouts of Taiwan's interchanges all at once is quite enjoyable.
						</p>
						<p class="text-gray-600 text-sm">
							有這個等級的細節後能夠做各種應用，但這裡就不一一講了，至少從平凡人的角度來說，可以一口氣欣賞台灣交流道漂亮的
							layout 其實也是不錯的。
						</p>
					</div>
				</div>
			</section>

			<!-- Data Source -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<Database class="w-6 h-6 text-green-600" />
					Data Source / 資料來源
				</h2>

				<div class="space-y-6">
					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Signal class="w-5 h-5 text-purple-600" />
							Data Access / 資料存取
						</h3>
						<p class="text-gray-700 mb-3">This project's data sources include:</p>
						<ul class="text-gray-700 space-y-1 mb-3 ml-4">
							<li>
								• <strong
									><a
										href="https://openstreetmap.org"
										target="_blank"
										rel="noopener"
										class="text-blue-600 hover:text-blue-800 underline">OSM</a
									></strong
								> - OpenStreetMap providing detailed road network data
							</li>
							<li>
								• <strong
									><a
										href="https://overpass-api.de/"
										target="_blank"
										rel="noopener"
										class="text-blue-600 hover:text-blue-800 underline">OVERPASS</a
									></strong
								> - API for querying OpenStreetMap data
							</li>
							<li>
								• <strong
									><a
										href="https://zh.wikipedia.org/"
										target="_blank"
										rel="noopener"
										class="text-blue-600 hover:text-blue-800 underline">Wikipedia</a
									></strong
								> - Structured interchange data from Taiwan highway Wikipedia pages
							</li>
							<li>
								• <strong
									><a
										href="https://www.freeway.gov.tw/"
										target="_blank"
										rel="noopener"
										class="text-blue-600 hover:text-blue-800 underline">交通部高速公路局</a
									></strong
								> - Official Taiwan freeway bureau data with facility information
							</li>
						</ul>
						<p class="text-gray-700 mb-3">
							Since the data is not synchronized in real-time, there might be discrepancies when
							cross-referencing. We apologize for any inconvenience.
						</p>
						<p class="text-gray-600 text-sm mb-3">
							此專案資料來源有 OSM（開放街圖）、OVERPASS（查詢 OSM 資料的
							API）、Wikipedia（維基百科台灣高速公路交流道文字資料）、交通部高速公路局（官方高速公路交流道與設施資料）。因為資料並非即時連動的，所以有可能你反查時會怪怪的，請見諒。
						</p>
						<p class="text-gray-700 mb-2">
							Last updated: <span
								class="bg-yellow-200 text-yellow-800 px-2 py-1 rounded text-sm font-semibold"
								>September 21, 2025</span
							>
						</p>
						<p class="text-gray-600 text-sm">資料最後更新時間: 2025年9月21日</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Globe class="w-5 h-5 text-blue-600" />
							OpenStreetMap (OSM)
						</h3>
						<p class="text-gray-700 mb-3">
							This project is built entirely on <a
								href="https://openstreetmap.org"
								target="_blank"
								rel="noopener"
								class="text-blue-600 hover:text-blue-800 underline">OpenStreetMap</a
							> data. I want to express my profound gratitude to the OSM community for maintaining such
							incredibly high-quality, open geographic data. Without their dedication and collaborative
							efforts, a project like this wouldn't be possible.
						</p>
						<p class="text-gray-600 text-sm">
							這個專案完全建立在 OpenStreetMap 資料之上。我要對 OSM
							社群維護如此高品質的開放地理資料表達深深的感謝。沒有他們的奉獻和協作努力，這樣的專案是不可能實現的。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Settings class="w-5 h-5 text-orange-600" />
							Data Processing Challenges / 資料處理挑戰
						</h3>
						<p class="text-gray-700 mb-3">
							While OSM contains incredibly detailed road network data, extracting
							interchange-specific information involves solving numerous technical challenges. Here
							we organize the data problems we overcame, which are essentially the features of this
							project.
						</p>
						<p class="text-gray-600 text-sm mb-3">
							雖然 OSM 包含極其詳細的道路網絡資料，但提取交流道特定資訊涉及解決眾多技術挑戰。
							這裡整理我們克服的資料問題，其實也就是這個 project 的特色。
						</p>

						<div class="grid md:grid-cols-2 gap-2 text-sm mb-4">
							{#each challenges as challenge}
								<div class="flex items-start">
									<span class="text-gray-700 mr-2">•</span>
									<div class="text-gray-700">{challenge.en}</div>
								</div>
								<div class="flex items-start">
									<span class="text-gray-700 mr-2">•</span>
									<div class="text-gray-700">{challenge.zh}</div>
								</div>
							{/each}
						</div>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Users class="w-5 h-5 text-green-600" />
							Community Contributions / 社群貢獻
						</h3>
						<p class="text-gray-700 mb-3">
							To develop this project, I also contributed some edits to OSM. These changes, besides
							fixing data issues and incompleteness, directly helped my program avoid additional
							logic complexity.
						</p>
						<p class="text-gray-600 text-sm mb-3">
							為了開發這個專案，我也編輯了一些條目到
							OSM。這些改動除了修正資料問題、不完整，直接幫到我的程式就不用更變邏輯了。
						</p>

						<div class="bg-blue-50 border-l-4 border-blue-400 p-4">
							<p class="text-blue-800 text-sm mb-2">
								Interestingly, I opened a discussion about inconsistent interchange exit naming
								(because I didn't dare to edit directly). The discussion concluded that according to
								OSM standards, original text should be preserved. A year later, someone had helped
								fix it, saving me from hardcoding in my program!
							</p>
							<p class="text-blue-700 text-sm">
								說個有趣的是，我有開啟一則討論有關交流道出口名稱不一致（因為我不敢改），而且討論結果是根據
								OSM 規範，保留原始文字，但這一年內回去看有人幫我改好了，這樣我就不用在程式內
								Hardcode 了！
							</p>
						</div>
					</div>
				</div>
			</section>

			<!-- Motivation -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<Lightbulb class="w-6 h-6 text-yellow-600" />
					Project Genesis / 專案起源
				</h2>

				<div class="space-y-6">
					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Zap class="w-5 h-5 text-yellow-600" />
							Born from Necessity / 源於需求
						</h3>
						<p class="text-gray-700 mb-3">
							This project originated from a sudden work requirement for detailed interchange data.
							Like any developer under pressure, I initially solved the immediate problem with the
							fastest, most brute-force approach available. Get the data, process it roughly,
							deliver the solution.
						</p>
						<p class="text-gray-600 text-sm">
							這個專案起源於工作中突然需要詳細的交流道資料。就像任何面臨壓力的開發者一樣，我最初用最快、最直接的方法解決了眼前的問題。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<RefreshCw class="w-5 h-5 text-blue-600" />
							The Complete Rewrite / 完全重寫
						</h3>
						<p class="text-gray-700 mb-3">
							However, the quick-and-dirty solution bothered me. I knew the problem deserved a more
							elegant, comprehensive approach. After a year of working on other projects, I came
							back to rebuild this from scratch with proper architecture, refined data processing,
							and careful attention to edge cases that the original version glossed over.
						</p>
						<p class="text-gray-600 text-sm">
							然而，這種粗糙的解決方案讓我困擾。我知道這個問題值得更優雅、更全面的方法。在做其他專案一年後，我決定從零開始重建，採用適當的架構、精緻的資料處理，並仔細關注原版本忽略的邊界情況。
						</p>
					</div>
				</div>
			</section>

			<!-- GitHub & Author -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<Link class="w-6 h-6 text-gray-800" />
					GitHub & Author / 原始碼與作者
				</h2>

				<!-- Author Section -->
				<div class="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
					<div class="flex items-center space-x-4">
						<div class="w-16 h-16 rounded-full overflow-hidden">
							<img
								src="https://avatars.githubusercontent.com/u/14067508?v=4"
								alt="linnil1"
								class="w-full h-full object-cover"
							/>
						</div>
						<div class="flex-1">
							<h3 class="text-lg font-medium text-gray-800">linnil1</h3>
							<p class="text-gray-600 text-sm mb-2">Author of Taiwan Interchange Explorer</p>
							<div class="flex space-x-3">
								<a
									href="https://github.com/linnil1"
									target="_blank"
									rel="noopener"
									class="bg-blue-100 text-blue-800 px-2 py-1 rounded text-xs hover:bg-blue-200"
									>GitHub</a
								>
								<a
									href="https://linnil1.tw"
									target="_blank"
									rel="noopener"
									class="bg-gray-200 text-gray-800 px-2 py-1 rounded text-xs hover:bg-gray-400"
									>Profile</a
								>
							</div>
						</div>
					</div>
				</div>

				<!-- Repository Section -->
				<div class="bg-gray-50 border border-gray-200 rounded-lg p-4">
					<div class="flex items-center space-x-4">
						<div class="w-16 h-16 rounded-full flex items-center justify-center">
							<SiGithub size={64} />
						</div>
						<div class="flex-1">
							<h3 class="text-lg font-medium text-gray-800">
								<a
									href="https://github.com/linnil1/taiwan_interchange"
									target="_blank"
									rel="noopener"
									class="text-blue-600 hover:text-blue-800"
								>
									linnil1 / taiwan_interchange
								</a>
							</h3>
							<p class="text-gray-600 text-sm mb-2">Taiwan Highway Interchange Explorer</p>
							<div class="flex flex-wrap gap-2">
								<span class="bg-blue-100 text-blue-800 px-2 py-1 rounded text-xs">Python</span>
								<span class="bg-green-100 text-green-800 px-2 py-1 rounded text-xs">Svelte</span>
								<span class="bg-purple-100 text-purple-800 px-2 py-1 rounded text-xs"
									>TypeScript</span
								>
								<span class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded text-xs"
									>OpenStreetMap</span
								>
							</div>
						</div>
					</div>
				</div>
			</section>

			<!-- Data Quality & Limitations -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<AlertTriangle class="w-6 h-6 text-amber-600" />
					Data Quality & Limitations / 資料品質與限制
				</h2>

				<div class="space-y-4">
					<div class="bg-yellow-50 border-l-4 border-yellow-400 p-4">
						<h3 class="font-medium text-yellow-800 mb-2">Data Accuracy / 資料準確性</h3>
						<p class="text-yellow-700 text-sm mb-2">
							This data is processed from OpenStreetMap and reflects the quality and completeness of
							OSM data at the time of extraction. While OSM data for Taiwan's highway system is
							generally excellent, there may be inconsistencies, missing information, or errors.
						</p>
						<p class="text-yellow-600 text-xs">
							此資料從 OpenStreetMap 處理而來，反映了提取時 OSM
							資料的品質和完整性。雖然台灣高速公路系統的 OSM
							資料通常很優秀，但可能存在不一致、缺失資訊或錯誤。
						</p>
					</div>
					<div class="bg-red-50 border-l-4 border-red-400 p-4">
						<h3 class="font-medium text-red-800 mb-2">Usage Disclaimer / 使用免責聲明</h3>
						<p class="text-red-700 text-sm mb-2">
							While this data is useful for analysis and development, it should not be used as the
							sole source for critical navigation or safety applications without proper validation
							and testing.
						</p>
						<p class="text-red-600 text-xs">
							雖然此資料對分析和開發很有用，但在沒有適當驗證和測試的情況下，不應將其作為關鍵導航或安全應用的唯一來源。
						</p>
					</div>
				</div>
			</section>

			<!-- License Information -->
			<section class="bg-white rounded-lg shadow-sm p-6">
				<h2 class="text-2xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
					<BookOpen class="w-6 h-6 text-green-600" />
					License Information / 授權資訊
				</h2>

				<div class="space-y-6">
					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Settings class="w-5 h-5 text-green-600" />
							Source Code License / 程式碼授權
						</h3>
						<p class="text-gray-700 mb-3">
							This project's source code is licensed under the
							<a
								href="https://www.gnu.org/licenses/gpl-3.0.html"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>GNU General Public License v3.0 (GPL-3.0)</strong>
							</a>. You are free to use, modify, and distribute the code, but any derivative works
							must also be licensed under GPL-3.0.
						</p>
						<p class="text-gray-600 text-sm">
							此專案的原始碼採用
							<a
								href="https://www.gnu.org/licenses/gpl-3.0.html"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>GNU 通用公共許可證 v3.0 (GPL-3.0)</strong>
							</a> 授權。 您可以自由使用、修改和分發程式碼，但任何衍生作品也必須採用 GPL-3.0 授權。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Database class="w-5 h-5 text-blue-600" />
							Data License / 資料授權
						</h3>
						<p class="text-gray-700 mb-3">
							The processed interchange data (<code class="bg-gray-100 px-1 rounded text-sm"
								>interchanges.json</code
							>) is licensed under
							<a
								href="https://creativecommons.org/licenses/by-sa/4.0/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong
									>Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)</strong
								>
							</a>. You may share and adapt the data, but must provide attribution and share
							derivatives under the same license.
						</p>
						<p class="text-gray-600 text-sm">
							處理後的交流道資料 (<code class="bg-gray-100 px-1 rounded text-sm"
								>interchanges.json</code
							>) 採用
							<a
								href="https://creativecommons.org/licenses/by-sa/4.0/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>創用CC 姓名標示-相同方式分享 4.0 國際 (CC BY-SA 4.0)</strong>
							</a> 授權。 您可以分享和改編資料，但必須提供署名並以相同授權分享衍生作品。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Globe class="w-5 h-5 text-purple-600" />
							OpenStreetMap Data / OpenStreetMap 資料
						</h3>
						<p class="text-gray-700 mb-3">
							The underlying geographic data is sourced from OpenStreetMap, which is licensed under
							the
							<a
								href="https://opendatacommons.org/licenses/odbl/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>Open Database License (ODbL)</strong>
							</a>. We acknowledge and thank the OSM community for their contributions.
						</p>
						<p class="text-gray-600 text-sm">
							基礎地理資料來源於 OpenStreetMap，採用
							<a
								href="https://opendatacommons.org/licenses/odbl/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>開放資料庫授權 (ODbL)</strong>
							</a>。 我們致謝 OSM 社群的貢獻。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<BookOpen class="w-5 h-5 text-orange-600" />
							Wikipedia Data / Wikipedia 資料
						</h3>
						<p class="text-gray-700 mb-3">
							Interchange text data extracted from Taiwan highway Wikipedia pages is available under
							<a
								href="https://creativecommons.org/licenses/by-sa/3.0/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0)</strong>
							</a>. We acknowledge Wikipedia contributors for maintaining detailed highway
							infrastructure information.
						</p>
						<p class="text-gray-600 text-sm">
							從台灣高速公路維基百科頁面提取的結構化交流道資料採用
							<a
								href="https://creativecommons.org/licenses/by-sa/3.0/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>創用CC 姓名標示-相同方式分享 3.0 (CC BY-SA 3.0)</strong>
							</a> 授權。我們感謝維基百科貢獻者維護詳細的公路基礎設施資訊。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Map class="w-5 h-5 text-red-600" />
							Government Data / 政府資料
						</h3>
						<p class="text-gray-700 mb-3">
							Highway interchange data from Taiwan's Freeway Bureau, Ministry of Transportation and
							Communications is available under the
							<a
								href="https://www.freeway.gov.tw/Publish.aspx?cnid=1660"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>Government Website Open Data Declaration (政府網站資料開放宣告)</strong>
							</a>. We acknowledge the
							<a
								href="https://www.freeway.gov.tw/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong
									>Freeway Bureau, Ministry of Transportation and Communications (交通部高速公路局)</strong
								>
							</a> for providing comprehensive official interchange and facility data.
						</p>
						<p class="text-gray-600 text-sm">
							來自台灣交通部高速公路局的高速公路交流道資料採用
							<a
								href="https://www.freeway.gov.tw/Publish.aspx?cnid=1660"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>政府網站資料開放宣告</strong>
							</a>
							授權。我們感謝
							<a
								href="https://www.freeway.gov.tw/"
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-600 hover:text-blue-800 underline font-medium"
							>
								<strong>交通部高速公路局</strong>
							</a> 提供全面的官方交流道和設施資料。
						</p>
					</div>

					<div>
						<h3 class="text-lg font-medium text-gray-700 mb-3 flex items-center gap-2">
							<Link class="w-5 h-5 text-gray-600" />
							Citation / 引用
						</h3>
						<p class="text-gray-700 mb-3">
							If you use our data or code, please cite our
							<strong>website</strong>
							or
							<strong>GitHub repository</strong>.
						</p>
						<p class="text-gray-600 text-sm">
							如果您使用我們的資料或程式碼，請引用我們的
							<strong>網站</strong>
							或
							<strong>GitHub Repo</strong>。
						</p>
					</div>
				</div>
			</section>
		</div>
	</div>
</div>
