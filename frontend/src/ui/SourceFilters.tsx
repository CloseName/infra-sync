import { health } from "./status";
import type { sourceQuery } from "./operations";
export function SourceFilters({
  query,
  sites,
  change,
  clear,
}: {
  query: ReturnType<typeof sourceQuery>;
  sites: string[];
  change: (key: string, value: string) => void;
  clear: () => void;
}) {
  return (
    <div className="table-toolbar" role="search" aria-label="Filter sources">
      <label className="search-field">
        Search sources
        <input
          type="search"
          value={query.q}
          placeholder="Name, source ID, address or target"
          onChange={(e) => change("q", e.target.value)}
        />
      </label>
      <div className="filter-field">
        <label htmlFor="filter-provider">Provider</label>
        <select
          id="filter-provider"
          value={query.provider}
          onChange={(e) => change("provider", e.target.value)}
        >
          <option value="">All providers</option>
          <option value="proxmox">Proxmox VE</option>
          <option value="esxi">VMware ESXi</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-sync-status">Sync status</label>
        <select
          id="filter-sync-status"
          value={query.health}
          onChange={(e) => change("health", e.target.value)}
        >
          <option value="">All states</option>
          {Object.entries(health).map(([key, value]) => (
            <option key={key} value={key}>
              {value.label}
            </option>
          ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-automatic-sync">Automatic sync</label>
        <select
          id="filter-automatic-sync"
          value={query.schedule}
          onChange={(e) => change("schedule", e.target.value)}
        >
          <option value="">On and off</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-attention">Attention</label>
        <select
          id="filter-attention"
          value={query.attention}
          onChange={(e) => change("attention", e.target.value)}
        >
          <option value="">All sources</option>
          <option value="yes">Needs attention</option>
          <option value="no">None reported</option>
          <option value="unknown">Not available</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-site">Site</label>
        <select
          id="filter-site"
          value={query.site}
          onChange={(e) => change("site", e.target.value)}
        >
          <option value="">All sites</option>
          {Array.from(new Set([...sites, ...(query.site ? [query.site] : [])]))
            .sort()
            .map((site) => (
              <option key={site}>{site}</option>
            ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-sort-by">Sort by</label>
        <select
          id="filter-sort-by"
          value={query.sort}
          onChange={(e) => change("sort", e.target.value)}
        >
          <option value="name">Source name</option>
          <option value="last">Last run</option>
          <option value="next">Next expected</option>
          <option value="attention">Attention</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-order">Order</label>
        <select
          id="filter-order"
          value={query.direction}
          onChange={(e) => change("direction", e.target.value)}
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      </div>
      <button onClick={() => clear()}>Clear filters</button>
    </div>
  );
}
