/**
 * FreshRoute notification feed.
 * Responsible for: showing receiver notifications newest-first with timestamps.
 * NOT responsible for: creating notifications or deciding who receives them.
 */

import { formatTime } from '../format'

export default function NotificationFeed({ state }) {
  const items = [...state.notifications].reverse()

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Receiver notifications</h2>
        <span className="count-badge">{items.length}</span>
      </div>

      {items.length === 0 ? (
        <p className="empty-state">
          Accepted reroutes will notify the cold storage, kitchen or shelter here.
        </p>
      ) : (
        <ul className="feed-list">
          {items.map((item) => (
            <li key={item.id} className="feed-item">
              <span className="feed-dot" />
              <div className="feed-body">
                <div className="feed-head">
                  <strong>{item.facility_name}</strong>
                  <span className="feed-time">{formatTime(item.timestamp)}</span>
                </div>
                <p>{item.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
