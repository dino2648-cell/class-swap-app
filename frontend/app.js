const { useEffect, useMemo, useRef, useState } = React;

const today = new Date().toISOString().slice(0, 10);
const dayNames = ["일", "월", "화", "수", "목", "금", "토"];
const schoolWeekdayNames = ["월", "화", "수", "목", "금"];
const weekdayPeriodLimits = [7, 7, 7, 7, 6];
const swapCandidateWeekTabs = [
  { value: 0, label: "이번 주" },
  { value: 1, label: "다음 주" },
];
const coverageCandidateTabs = [
  { value: "available", label: "보강 가능" },
  { value: "busy", label: "수업 중" },
];

function parseDateValue(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function formatDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(dateValue, amount) {
  const date = parseDateValue(dateValue);
  date.setDate(date.getDate() + amount);
  return formatDateValue(date);
}

function formatDateWithDay(dateValue) {
  if (!dateValue) return "";
  const date = parseDateValue(dateValue);
  return `${dateValue.slice(5).replace("-", ".")}(${dayNames[date.getDay()]})`;
}

function formatCurrency(value) {
  return `${Number(value || 0).toLocaleString("ko-KR")}원`;
}

function BrandLogoIcon() {
  return (
    <svg className="brand-logo-icon" viewBox="0 0 220 220" aria-hidden="true">
      <path
        className="brand-logo-arrow"
        d="M111 24c31 0 59 15 77 39l10-10c5-5 14-1 14 6v42c0 7-8 11-14 6l-36-30c-4-4-4-10 0-14l8-8c-15-16-36-26-59-26-42 0-77 31-82 72-1 6-6 10-12 9s-10-7-9-13c6-52 50-73 103-73Z"
      />
      <path
        className="brand-logo-arrow"
        d="M109 196c-31 0-59-15-77-39l-10 10c-5 5-14 1-14-6v-42c0-7 8-11 14-6l36 30c4 4 4 10 0 14l-8 8c15 16 36 26 59 26 42 0 77-31 82-72 1-6 6-10 12-9s10 7 9 13c-6 52-50 73-103 73Z"
      />
      <path
        className="brand-logo-book"
        d="M54 78c23 0 43 8 56 26 13-18 33-26 56-26v68c-23 0-41 8-56 25-15-17-33-25-56-25V78Z"
      />
      <path className="brand-logo-page" d="M110 103v68" />
    </svg>
  );
}

function requestStatusLabel(status) {
  return {
    pending: "대기",
    accepted: "반영 중",
    rejected: "거절",
    expired: "만료",
    cancelled: "취소",
  }[status] || status || "";
}

function getWeekOfMonth(dateValue) {
  const date = parseDateValue(dateValue);
  const firstDay = new Date(date.getFullYear(), date.getMonth(), 1);
  const mondayOffset = (firstDay.getDay() + 6) % 7;
  return Math.floor((date.getDate() + mondayOffset - 1) / 7) + 1;
}

function getWeeklyMeta(anchorDate, weekly) {
  const weekStart = weekly?.week_start || anchorDate;
  const weekEnd = weekly?.week_end || addDays(weekStart, 4);
  const baseDate = parseDateValue(weekStart);
  return {
    title: `${baseDate.getFullYear()}년 ${baseDate.getMonth() + 1}월 ${getWeekOfMonth(weekStart)}주차`,
    range: `${formatDateWithDay(weekStart)} ~ ${formatDateWithDay(weekEnd)}`,
    anchor: `기준일 ${formatDateWithDay(anchorDate)}`,
  };
}

function extractErrorMessage(error) {
  if (!error) {
    return "알 수 없는 오류가 발생했습니다.";
  }
  if (typeof error === "string") {
    return error;
  }
  if (Array.isArray(error)) {
    return error.map(extractErrorMessage).join("\n");
  }
  if (typeof error === "object") {
    if (typeof error.detail === "string") {
      return error.detail;
    }
    if (Array.isArray(error.detail)) {
      return error.detail.map(extractErrorMessage).join("\n");
    }
    if (error.detail && typeof error.detail === "object") {
      if (Array.isArray(error.detail.errors)) {
        return error.detail.errors.join("\n");
      }
      return JSON.stringify(error.detail, null, 2);
    }
    if (Array.isArray(error.errors)) {
      return error.errors.join("\n");
    }
  }
  return "요청 처리 중 오류가 발생했습니다.";
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    throw payload;
  }
  return payload;
}

function statusTextForCell(cell) {
  if (!cell) return "free";
  return cell.status || cell.slot_type || "free";
}

function prettySlot(cell) {
  const effective = cell?.effective || cell;
  if (!effective) return "공강";
  if (effective.slot_type === "travel") {
    return `${effective.location_label} · 순회`;
  }
  if (effective.slot_type === "class") {
    return `${effective.class_code} ${effective.subject}`;
  }
  return "공강";
}

function isOutgoingStatus(status) {
  return status === "swapped-out" || status === "coverage-out" || status === "coverage-pending-out";
}

function StatusBanner({ status, tone = "info", onDismiss }) {
  if (!status) return null;
  return (
    <div className={`status ${tone === "error" ? "error" : tone === "success" ? "success" : ""}`}>
      <span>{status}</span>
      {onDismiss ? (
        <button className="status-dismiss" type="button" onClick={onDismiss} aria-label="상태 알림 닫기">
          확인
        </button>
      ) : null}
    </div>
  );
}

function ScheduleCell({ cell }) {
  const status = statusTextForCell(cell);
  const isSwapOut = status === "swapped-out";
  const isSwapIn = status === "swapped-in";
  const isCoverageOut = status === "coverage-out" || status === "coverage-pending-out";
  const isCoverageIn = status === "coverage-in" || status === "coverage-pending-in";
  return (
    <div className={`schedule-cell ${status}`}>
      <div className="slot-title">
        {status === "free"
          ? "공강"
          : status === "holiday"
            ? cell?.label || "수업 없음"
          : isSwapOut
            ? "내 수업 교체됨"
          : isSwapIn
            ? `교체 · ${prettySlot(cell)}`
            : isCoverageOut
              ? status === "coverage-pending-out"
                ? "보강 요청 중"
                : "보강 배정됨"
              : isCoverageIn
                ? `보강 · ${prettySlot(cell)}`
              : prettySlot(cell)}
      </div>
      {cell?.original && isOutgoingStatus(status) ? (
        <div className="slot-sub strike">{prettySlot(cell.original)}</div>
      ) : null}
      {cell?.original?.swap_with_name && isSwapOut ? (
        <div className="slot-sub">교체 상대: {cell.original.swap_with_name}</div>
      ) : null}
      {cell?.original?.covered_by_name && isCoverageOut ? (
        <div className="slot-sub">보강 담당: {cell.original.covered_by_name}</div>
      ) : null}
      {cell?.effective?.from_teacher_name ? (
        <div className="slot-sub">{isCoverageIn ? "보강 원 담당" : "원 담당"}: {cell.effective.from_teacher_name}</div>
      ) : null}
      {isSwapIn ? <div className="slot-sub swap-label">교체 수업</div> : null}
      {isSwapOut ? <div className="slot-sub swap-label">내 수업 교체됨</div> : null}
      {isCoverageIn ? <div className="slot-sub coverage-label">보강 수업</div> : null}
      {cell?.original && status === "swapped-in" ? (
        <div className="slot-sub">원래 내 일정: {prettySlot(cell.original)}</div>
      ) : null}
      {cell?.effective?.location_label && status !== "free" ? (
        <div className="slot-sub">{cell.effective.location_label}</div>
      ) : null}
      {!cell?.effective && status === "swapped-out" ? <div className="slot-sub">해당 시간엔 수업이 없습니다.</div> : null}
    </div>
  );
}

function WeeklyGrid({ weekly }) {
  if (!weekly?.days?.length) {
    return <div className="empty">아직 업로드된 주간 시간표가 없습니다.</div>;
  }

  const periods = [1, 2, 3, 4, 5, 6, 7];
  return (
    <div className="weekly-grid">
      <div className="weekly-head">교시</div>
      {weekly.days.map((day) => (
        <div key={day.weekday} className="weekly-head">
          <strong>{day.day_label}</strong>
          {day.date ? <small>{day.date.slice(5)}</small> : null}
        </div>
      ))}
      {periods.map((period) => (
        <React.Fragment key={period}>
          <div className="period-cell">{period}</div>
          {weekly.days.map((day) => {
            const cell = day.periods.find((item) => item.period === period) || { slot_type: "free" };
            return <ScheduleCell key={`${day.weekday}-${period}`} cell={cell} />;
          })}
        </React.Fragment>
      ))}
    </div>
  );
}

function SwapRequestCard({ request, onAccept, onReject, onDismiss }) {
  return (
    <div className={`request-card ${request.status}`}>
      <div className="panel-header">
        <div>
          <h4>
            {request.source_date} {request.source_period}교시 ↔ {request.target_date} {request.target_period}교시
          </h4>
          <div className="panel-copy">
            {request.source_class_code} {request.source_subject} / {request.target_class_code} {request.target_subject}
          </div>
        </div>
        <span className={`status-chip ${request.status}`}>{request.status}</span>
      </div>
      <div className="chip-row">
        <span className="chip">요청자 {request.requester_name}</span>
        <span className="chip">상대 {request.responder_name}</span>
      </div>
      {request.response_note ? <div className="tiny">메모: {request.response_note}</div> : null}
      {onAccept || onReject || onDismiss ? (
        <div className="button-row" style={{ marginTop: "12px" }}>
          {onAccept ? (
            <button className="button primary" onClick={() => onAccept(request.id)}>
              수락
            </button>
          ) : null}
          {onReject ? (
            <button className="button warn" onClick={() => onReject(request.id)}>
              거절
            </button>
          ) : null}
          {onDismiss ? (
            <button className="button ghost" onClick={() => onDismiss(request.id)}>
              확인 후 삭제
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CoverageRequestCard({ request, onAccept, onReject, onDismiss }) {
  return (
    <div className={`request-card ${request.status}`}>
      <div className="panel-header">
        <div>
          <h4>
            {request.class_date} {request.day_label} {request.period}교시 보강
          </h4>
          <div className="panel-copy">
            {request.class_code} {request.subject}
          </div>
        </div>
        <span className={`status-chip ${request.status}`}>{request.status}</span>
      </div>
      <div className="chip-row">
        <span className="chip">요청자 {request.requester_name}</span>
        <span className="chip">보강 후보 {request.responder_name}</span>
      </div>
      {request.response_note ? <div className="tiny">메모: {request.response_note}</div> : null}
      {onAccept || onReject || onDismiss ? (
        <div className="button-row" style={{ marginTop: "12px" }}>
          {onAccept ? (
            <button className="button primary" onClick={() => onAccept(request.id)}>
              수락
            </button>
          ) : null}
          {onReject ? (
            <button className="button warn" onClick={() => onReject(request.id)}>
              거절
            </button>
          ) : null}
          {onDismiss ? (
            <button className="button ghost" onClick={() => onDismiss(request.id)}>
              확인 후 삭제
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function NotificationPanel({ notifications, onMarkAll, onDeleteNotification }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3>알림</h3>
          <div className="panel-copy">요청 결과와 관리자 안내를 한곳에서 확인합니다.</div>
        </div>
        <div className="button-row">
          <button className="button ghost" onClick={onMarkAll}>
            모두 확인 후 삭제
          </button>
        </div>
      </div>
      {!notifications?.items?.length ? (
        <div className="empty">새 알림이 없습니다.</div>
      ) : (
        <div className="tableish">
          {notifications.items.map((item) => (
            <div key={item.id} className="list-card">
              <div className="panel-header">
                <div>
                  <strong>{item.title}</strong>
                  <div className="tiny">{item.category}</div>
                </div>
                <div className="button-row">
                  <span className="chip">새 알림</span>
                  <button className="button tiny-button" onClick={() => onDeleteNotification(item.id)}>
                    삭제
                  </button>
                </div>
              </div>
              <div className="panel-copy">{item.message}</div>
              <div className="tiny">{item.created_at}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PersonalStatusPanel({
  user,
  swapRequests,
  coverageRequests,
  onCancelSwap,
  onCancelCoverage,
  onDismissSwap,
  onDismissCoverage,
}) {
  const buildSwapItem = (request, direction) => ({
    id: `swap-${direction}-${request.id}`,
    type: "swap",
    typeLabel: "교체",
    request,
    direction,
    date: request.source_date,
    period: request.source_period,
    status: request.status,
    counterpartName: direction === "sent" ? request.responder_name : request.requester_name,
    summary: `${request.source_date} ${request.source_period}교시 ${request.source_class_code} ${request.source_subject} ↔ ${request.target_date} ${request.target_period}교시 ${request.target_class_code} ${request.target_subject}`,
  });
  const buildCoverageItem = (request, direction) => ({
    id: `coverage-${direction}-${request.id}`,
    type: "coverage",
    typeLabel: "보강",
    request,
    direction,
    date: request.class_date,
    period: request.period,
    status: request.status,
    counterpartName: direction === "sent" ? request.responder_name : request.requester_name,
    summary: `${request.class_date} ${request.day_label} ${request.period}교시 ${request.class_code} ${request.subject}`,
  });
  const statusCoverageSent = coverageRequests.status_sent || coverageRequests.sent || [];
  const statusCoverageReceived = coverageRequests.status_received || coverageRequests.received || [];
  const statusSwapSent = swapRequests.status_sent || swapRequests.sent || [];
  const statusSwapReceived = swapRequests.status_received || swapRequests.received || [];
  const items = [
    ...statusCoverageSent.map((request) => buildCoverageItem(request, "sent")),
    ...statusCoverageReceived.map((request) => buildCoverageItem(request, "received")),
    ...statusSwapSent.map((request) => buildSwapItem(request, "sent")),
    ...statusSwapReceived.map((request) => buildSwapItem(request, "received")),
  ].sort((a, b) => `${b.date}-${b.period}`.localeCompare(`${a.date}-${a.period}`));
  const activeItems = items.filter((item) => item.status === "pending" || item.status === "accepted");
  const closedItems = items.filter((item) => item.status !== "pending" && item.status !== "accepted");

  const canCancel = (item) =>
    item.status === "accepted" || (item.status === "pending" && item.request.requester_id === user.id);
  const cancelItem = (item) =>
    item.type === "coverage" ? onCancelCoverage(item.request.id) : onCancelSwap(item.request.id);
  const dismissItem = (item) =>
    item.type === "coverage" ? onDismissCoverage(item.request.id) : onDismissSwap(item.request.id);
  const canDismiss = (item) =>
    item.status !== "pending" &&
    ((item.direction === "sent" && !item.request.requester_hidden) ||
      (item.direction === "received" && !item.request.responder_hidden));

  const renderItem = (item) => (
    <div key={item.id} className={`request-card ${item.status}`}>
      <div className="panel-header">
        <div>
          <strong>
            {item.typeLabel} · {item.direction === "sent" ? "내가 요청" : "내가 받음"}
          </strong>
          <div className="panel-copy">{item.summary}</div>
        </div>
        <span className={`status-chip ${item.status}`}>{item.status}</span>
      </div>
      <div className="chip-row">
        <span className="chip">상대 {item.counterpartName}</span>
        <span className="chip">{item.date}</span>
      </div>
      {item.request.response_note ? <div className="tiny">메모: {item.request.response_note}</div> : null}
      <div className="button-row" style={{ marginTop: "12px" }}>
        {canCancel(item) ? (
          <button className="button warn" onClick={() => cancelItem(item)}>
            {item.status === "pending" ? "요청 취소" : "확정 취소"}
          </button>
        ) : null}
        {item.status === "pending" && item.direction === "received" ? (
          <span className="tiny">수락/거절은 알림·요청함에서 처리합니다.</span>
        ) : null}
        {canDismiss(item) ? (
          <button className="button ghost" onClick={() => dismissItem(item)}>
            확인 후 삭제
          </button>
        ) : null}
      </div>
    </div>
  );

  return (
    <div className="stack tab-panel-anchor" data-tab-panel="status">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>교체·보강 현황</h3>
            <div className="panel-copy">
              현재 요청 중이거나 확정 반영된 교체·보강을 확인하고 필요한 경우 취소할 수 있습니다.
            </div>
          </div>
          <span className="chip">{activeItems.length}건 진행 중</span>
        </div>
        {!activeItems.length ? (
          <div className="empty">진행 중인 교체·보강 내역이 없습니다.</div>
        ) : (
          <div className="tableish">{activeItems.map(renderItem)}</div>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>종료된 내역</h3>
            <div className="panel-copy">거절·취소·만료된 요청입니다. 내가 확인한 내역은 목록에서 삭제할 수 있습니다.</div>
          </div>
        </div>
        {!closedItems.length ? (
          <div className="empty">종료된 교체·보강 내역이 없습니다.</div>
        ) : (
          <div className="tableish">{closedItems.map(renderItem)}</div>
        )}
      </div>
    </div>
  );
}

function PlanPanel({ planDate, setPlanDate, weeklyPlan, onReloadPlan, isAdmin }) {
  const xlsxDownloadUrl = `/api/plans/weekly/download?date=${planDate}`;
  const pdfDownloadUrl = `/api/plans/weekly/download.pdf?date=${planDate}`;
  const schoolWeeklyDownloadUrl = `/api/admin/schedule/weekly/download?date=${planDate}`;
  const scopeLabel = isAdmin ? "전체 확정 내역" : "나와 관련된 확정 내역";
  return (
    <div className="stack tab-panel-anchor" data-tab-panel="plan">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>결보강계획서 작성</h3>
            <div className="panel-copy">
              선택한 날짜가 속한 주의 {scopeLabel}을 조회하고 계획서 파일로 내려받습니다.
            </div>
          </div>
          <div className="button-row">
            <input
              className="input"
              style={{ maxWidth: "180px" }}
              type="date"
              value={planDate}
              onChange={(event) => setPlanDate(event.target.value)}
            />
            <button className="button secondary" onClick={onReloadPlan}>
              조회
            </button>
            <a className="button primary" href={xlsxDownloadUrl}>
              엑셀 내려받기
            </a>
            <a className="button secondary" href={pdfDownloadUrl}>
              PDF 내려받기
            </a>
            {isAdmin ? (
              <a className="button reset" href={schoolWeeklyDownloadUrl}>
                주간 전체 시간표 엑셀
              </a>
            ) : null}
          </div>
        </div>
        {weeklyPlan ? (
          <div className="plan-summary">
            <div className="roster-metric">
              <span>기간</span>
              <strong>
                {weeklyPlan.week_start} ~ {weeklyPlan.week_end}
              </strong>
            </div>
            <div className="roster-metric">
              <span>교체 요청</span>
              <strong>{weeklyPlan.summary.swap_request_count}</strong>
            </div>
            <div className="roster-metric">
              <span>보강 요청</span>
              <strong>{weeklyPlan.summary.coverage_request_count}</strong>
            </div>
            <div className="roster-metric">
              <span>작성 행</span>
              <strong>{weeklyPlan.summary.row_count}</strong>
            </div>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>주간 결보강 내역</h3>
            <div className="panel-copy">계획서 파일에 들어갈 {scopeLabel}입니다.</div>
          </div>
        </div>
        {!weeklyPlan ? (
          <div className="empty">조회할 주를 선택해 주세요.</div>
        ) : !weeklyPlan.items.length ? (
          <div className="empty">해당 주의 확정된 교체·보강 내역이 없습니다.</div>
        ) : (
          <div className="plan-table">
            <div className="plan-row header">
              <span>구분</span>
              <span>일자</span>
              <span>교시</span>
              <span>수업</span>
              <span>원 담당</span>
              <span>보강/교체</span>
              <span>내용</span>
            </div>
            {weeklyPlan.items.map((item) => (
              <div key={item.id} className="plan-row">
                <span>
                  <strong>{item.type}</strong>
                </span>
                <span>
                  {item.date}
                  <small>{item.day_label}</small>
                </span>
                <span>{item.period}교시</span>
                <span>
                  {item.class_code} {item.subject}
                </span>
                <span>{item.original_teacher_name}</span>
                <span>{item.assigned_teacher_name}</span>
                <span>{item.detail}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EventCoveragePanel({ teachers, onComplete }) {
  const teacherOptions = teachers.filter((teacher) => teacher.role === "teacher");
  const [form, setForm] = useState({
    title: "기능경기대회",
    startDate: today,
    endDate: addDays(today, 4),
  });
  const [selectedTeacherIds, setSelectedTeacherIds] = useState([]);
  const [preview, setPreview] = useState(null);
  const [assignments, setAssignments] = useState({});
  const [status, setStatus] = useState("");
  const [tone, setTone] = useState("info");
  const [loading, setLoading] = useState(false);

  const toggleTeacher = (teacherId) => {
    setSelectedTeacherIds((current) =>
      current.includes(teacherId) ? current.filter((id) => id !== teacherId) : [...current, teacherId],
    );
  };

  const defaultAssignments = (payload) =>
    (payload.affected_slots || []).reduce((next, slot) => {
      if (slot.can_request && slot.recommended_teacher_id) {
        next[slot.id] = String(slot.recommended_teacher_id);
      }
      return next;
    }, {});

  const loadPreview = async () => {
    if (!selectedTeacherIds.length) {
      setStatus("부재 교사를 1명 이상 선택해 주세요.");
      setTone("error");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      const payload = await apiFetch("/api/admin/event-coverage/preview", {
        method: "POST",
        body: JSON.stringify({
          title: form.title,
          start_date: form.startDate,
          end_date: form.endDate,
          absent_teacher_ids: selectedTeacherIds,
        }),
      });
      setPreview(payload);
      setAssignments(defaultAssignments(payload));
      setTone("success");
      setStatus("행사 기간의 결강 수업과 보강 후보를 조회했습니다.");
    } catch (error) {
      setPreview(null);
      setAssignments({});
      setTone("error");
      setStatus(extractErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const selectedAssignments = () =>
    (preview?.affected_slots || [])
      .filter((slot) => slot.can_request && assignments[slot.id])
      .map((slot) => ({
        requester_id: slot.requester_id,
        class_date: slot.class_date,
        period: slot.period,
        responder_id: Number(assignments[slot.id]),
      }));

  const submitBulkRequests = async () => {
    const payloadAssignments = selectedAssignments();
    if (!payloadAssignments.length) {
      setStatus("요청을 보낼 보강 배정을 1건 이상 선택해 주세요.");
      setTone("error");
      return;
    }
    if (!window.confirm(`${payloadAssignments.length}건의 보강 요청을 일괄 전송할까요?`)) return;
    setLoading(true);
    setStatus("");
    try {
      const result = await apiFetch("/api/admin/event-coverage/requests", {
        method: "POST",
        body: JSON.stringify({
          title: form.title,
          assignments: payloadAssignments,
        }),
      });
      setTone(result.summary.error_count ? "error" : "success");
      setStatus(
        `보강 요청 ${result.summary.created_count}건을 전송했습니다.${
          result.summary.error_count ? ` 실패 ${result.summary.error_count}건은 다시 확인해 주세요.` : ""
        }`,
      );
      await onComplete?.();
      await loadPreview();
    } catch (error) {
      setTone("error");
      setStatus(extractErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const assignableCount = selectedAssignments().length;

  return (
    <div className="stack tab-panel-anchor" data-tab-panel="event">
      <div className="panel event-panel">
        <div className="panel-header">
          <div>
            <h3>행사 보강 일괄 처리</h3>
            <div className="panel-copy">
              대회·캠프·출장처럼 여러 교사가 장기간 부재할 때 결강 수업과 보강 후보를 한 번에 조회합니다.
            </div>
          </div>
          <div className="button-row">
            <button className="button primary" onClick={loadPreview} disabled={loading}>
              {loading ? "조회 중..." : "계획 생성"}
            </button>
            <button className="button secondary" onClick={submitBulkRequests} disabled={!preview || loading}>
              선택 요청 전송
            </button>
          </div>
        </div>
        <StatusBanner status={status} tone={tone} onDismiss={() => setStatus("")} />
        <div className="event-form-grid">
          <label className="field">
            <span className="field-title">행사명</span>
            <input
              className="input"
              value={form.title}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="예: 기능경기대회"
            />
          </label>
          <label className="field">
            <span className="field-title">시작일</span>
            <input
              className="input"
              type="date"
              value={form.startDate}
              onChange={(event) => setForm((current) => ({ ...current, startDate: event.target.value }))}
            />
          </label>
          <label className="field">
            <span className="field-title">종료일</span>
            <input
              className="input"
              type="date"
              value={form.endDate}
              onChange={(event) => setForm((current) => ({ ...current, endDate: event.target.value }))}
            />
          </label>
        </div>
        <div className="event-teacher-picker">
          <div className="panel-header compact">
            <div>
              <h4>부재 교사 선택</h4>
              <div className="panel-copy">선택된 교사는 보강 후보에서도 자동 제외됩니다.</div>
            </div>
            <span className="chip">{selectedTeacherIds.length}명 선택</span>
          </div>
          <div className="event-teacher-grid">
            {teacherOptions.map((teacher) => (
              <label
                key={teacher.id}
                className={`event-teacher-chip ${selectedTeacherIds.includes(teacher.id) ? "active" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={selectedTeacherIds.includes(teacher.id)}
                  onChange={() => toggleTeacher(teacher.id)}
                />
                <span>
                  <strong>{teacher.display_name}</strong>
                  <small>{teacher.username}</small>
                </span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {preview ? (
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>행사 보강 계획</h3>
              <div className="panel-copy">
                {preview.start_date} ~ {preview.end_date} · {preview.absent_teachers.length}명 부재
              </div>
            </div>
            <span className="chip">{assignableCount}건 선택됨</span>
          </div>
          <div className="plan-summary">
            <div className="roster-metric">
              <span>결강 수업</span>
              <strong>{preview.summary.affected_slot_count}</strong>
            </div>
            <div className="roster-metric">
              <span>배정 가능</span>
              <strong>{preview.summary.assignable_slot_count}</strong>
            </div>
            <div className="roster-metric">
              <span>후보 없음</span>
              <strong>{preview.summary.no_candidate_count}</strong>
            </div>
            <div className="roster-metric">
              <span>잠금/마감</span>
              <strong>{preview.summary.locked_slot_count}</strong>
            </div>
          </div>
          {preview.skipped_days.length ? (
            <div className="info-strip">
              제외된 날짜: {preview.skipped_days.map((day) => `${day.date}(${day.reason})`).join(", ")}
            </div>
          ) : null}
          {!preview.affected_slots.length ? (
            <div className="empty">선택 기간에 결강 처리할 정규수업이 없습니다.</div>
          ) : (
            <div className="event-slot-list">
              {preview.affected_slots.map((slot) => {
                const disabled = !slot.can_request || !slot.candidates.length;
                return (
                  <div key={slot.id} className={`event-slot-row ${disabled ? "disabled" : ""}`}>
                    <div className="event-slot-main">
                      <strong>
                        {formatDateWithDay(slot.class_date)} · {slot.period}교시
                      </strong>
                      <span>
                        {slot.requester_name} · {slot.class_code} {slot.subject}
                      </span>
                    </div>
                    <div className="event-slot-candidates">
                      {disabled ? (
                        <span className="status-chip cancelled">
                          {slot.locked || !slot.can_request ? "잠금/마감" : "후보 없음"}
                        </span>
                      ) : (
                        <select
                          className="select"
                          value={assignments[slot.id] || ""}
                          onChange={(event) =>
                            setAssignments((current) => ({ ...current, [slot.id]: event.target.value }))
                          }
                        >
                          <option value="">배정 안 함</option>
                          {slot.candidates.map((candidate) => (
                            <option key={candidate.teacher_id} value={candidate.teacher_id}>
                              {candidate.teacher_name} · 당일 수업 {candidate.day_class_count}건 · 순회{" "}
                              {candidate.day_travel_count}건
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                    <div className="event-slot-meta">
                      <span>후보 {slot.candidate_count}명</span>
                      {slot.recommended_teacher_name ? <span>추천 {slot.recommended_teacher_name}</span> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function emptyAdminSlotDraft(teacherId = "") {
  return {
    teacher_id: teacherId ? String(teacherId) : "",
    weekday: "0",
    period: "1",
    slot_type: "class",
    class_code: "",
    subject: "",
    location_label: "",
  };
}

function buildAdminSlotPayload(draft, fallbackTeacherId) {
  return {
    teacher_id: Number(draft.teacher_id || fallbackTeacherId),
    weekday: Number(draft.weekday),
    period: Number(draft.period),
    slot_type: draft.slot_type || "class",
    class_code: draft.class_code || "",
    subject: draft.subject || "",
    location_label: draft.location_label || "",
  };
}

function AdminSlotForm({ draft, setDraft, onSubmit, submitLabel, onCancel }) {
  const weekday = Number(draft.weekday || 0);
  const periodLimit = weekdayPeriodLimits[weekday] || 7;
  const updateDraft = (patch) => {
    setDraft((prev) => {
      const next = { ...prev, ...patch };
      const nextWeekday = Number(next.weekday || 0);
      const nextLimit = weekdayPeriodLimits[nextWeekday] || 7;
      if (Number(next.period || 1) > nextLimit) {
        next.period = String(nextLimit);
      }
      return next;
    });
  };

  return (
    <div className="slot-edit-form">
      <select className="select" value={draft.weekday} onChange={(event) => updateDraft({ weekday: event.target.value })}>
        {schoolWeekdayNames.map((label, index) => (
          <option key={label} value={index}>
            {label}
          </option>
        ))}
      </select>
      <select className="select" value={draft.period} onChange={(event) => updateDraft({ period: event.target.value })}>
        {Array.from({ length: periodLimit }, (_, index) => index + 1).map((period) => (
          <option key={period} value={period}>
            {period}교시
          </option>
        ))}
      </select>
      <select className="select" value={draft.slot_type} onChange={(event) => updateDraft({ slot_type: event.target.value })}>
        <option value="class">정규 수업</option>
        <option value="travel">순회</option>
      </select>
      {draft.slot_type === "travel" ? (
        <input
          className="input"
          type="text"
          placeholder="순회 학교명"
          value={draft.location_label}
          onChange={(event) => updateDraft({ location_label: event.target.value })}
        />
      ) : (
        <>
          <input
            className="input"
            type="text"
            placeholder="학반 예: 103 또는 중1"
            value={draft.class_code}
            onChange={(event) => updateDraft({ class_code: event.target.value })}
          />
          <input
            className="input"
            type="text"
            placeholder="과목명"
            value={draft.subject}
            onChange={(event) => updateDraft({ subject: event.target.value })}
          />
        </>
      )}
      <div className="button-row compact">
        <button className="button primary" onClick={onSubmit}>
          {submitLabel}
        </button>
        {onCancel ? (
          <button className="button ghost" onClick={onCancel}>
            취소
          </button>
        ) : null}
      </div>
    </div>
  );
}

function AdminTimetableManager({ teachers, slots, onCreateSlot, onUpdateSlot, onDeleteSlot }) {
  const teacherOptions = teachers.filter((teacher) => teacher.role === "teacher");
  const [selectedTeacherId, setSelectedTeacherId] = useState("");
  const [newSlotDraft, setNewSlotDraft] = useState(emptyAdminSlotDraft(""));
  const [editingSlotId, setEditingSlotId] = useState(null);
  const [editingDraft, setEditingDraft] = useState(emptyAdminSlotDraft(""));

  useEffect(() => {
    if (!teacherOptions.length) {
      setSelectedTeacherId("");
      return;
    }
    const stillExists = teacherOptions.some((teacher) => String(teacher.id) === String(selectedTeacherId));
    if (!selectedTeacherId || !stillExists) {
      setSelectedTeacherId(String(teacherOptions[0].id));
    }
  }, [teachers, selectedTeacherId]);

  useEffect(() => {
    setNewSlotDraft((prev) => ({ ...prev, teacher_id: selectedTeacherId || "" }));
  }, [selectedTeacherId]);

  const selectedTeacher = teacherOptions.find((teacher) => String(teacher.id) === String(selectedTeacherId));
  const selectedSlots = slots
    .filter((slot) => String(slot.teacher_id) === String(selectedTeacherId))
    .sort((a, b) => a.weekday - b.weekday || a.period - b.period);
  const slotsByWeekday = schoolWeekdayNames.map((_, weekday) =>
    selectedSlots.filter((slot) => slot.weekday === weekday),
  );

  const startEdit = (slot) => {
    setEditingSlotId(slot.id);
    setEditingDraft({
      teacher_id: String(slot.teacher_id),
      weekday: String(slot.weekday),
      period: String(slot.period),
      slot_type: slot.slot_type,
      class_code: slot.class_code || "",
      subject: slot.subject || "",
      location_label: slot.location_label || "",
    });
  };

  const createSlot = async () => {
    await onCreateSlot(buildAdminSlotPayload(newSlotDraft, selectedTeacherId));
    setNewSlotDraft(emptyAdminSlotDraft(selectedTeacherId));
  };

  const updateSlot = async () => {
    await onUpdateSlot(editingSlotId, buildAdminSlotPayload(editingDraft, selectedTeacherId));
    setEditingSlotId(null);
  };

  const deleteSlot = async (slot) => {
    if (!window.confirm(`${slot.day_label} ${slot.period}교시 수업을 삭제할까요?`)) return;
    await onDeleteSlot(slot.id);
    if (editingSlotId === slot.id) {
      setEditingSlotId(null);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3>교사별 주간 시간표 직접 관리</h3>
          <div className="panel-copy">엑셀 재업로드 없이 교사별 요일·교시·학반·과목을 바로 보정합니다.</div>
        </div>
        <select className="select admin-teacher-select" value={selectedTeacherId} onChange={(event) => setSelectedTeacherId(event.target.value)}>
          {teacherOptions.map((teacher) => (
            <option key={teacher.id} value={teacher.id}>
              {teacher.display_name}
            </option>
          ))}
        </select>
      </div>

      {!teacherOptions.length ? (
        <div className="empty">등록된 교사 계정이 없습니다. 먼저 회원·교사 관리에서 교사를 추가해 주세요.</div>
      ) : (
        <div className="stack">
          <div className="info-strip">
            {selectedTeacher?.display_name || "선택한 교사"} · 등록 수업 {selectedSlots.filter((slot) => slot.slot_type === "class").length}건 · 순회{" "}
            {selectedSlots.filter((slot) => slot.slot_type === "travel").length}건
          </div>

          <div className="timetable-editor-grid">
            {schoolWeekdayNames.map((label, weekday) => (
              <div key={label} className="timetable-day-column">
                <div className="timetable-day-title">
                  <strong>{label}</strong>
                  <span>{weekdayPeriodLimits[weekday]}교시</span>
                </div>
                {!slotsByWeekday[weekday].length ? (
                  <div className="empty compact">등록된 수업이 없습니다.</div>
                ) : (
                  <div className="slot-list">
                    {slotsByWeekday[weekday].map((slot) => (
                      <div key={slot.id} className={`slot-admin-card ${slot.slot_type}`}>
                        {editingSlotId === slot.id ? (
                          <AdminSlotForm
                            draft={editingDraft}
                            setDraft={setEditingDraft}
                            submitLabel="수정 저장"
                            onSubmit={updateSlot}
                            onCancel={() => setEditingSlotId(null)}
                          />
                        ) : (
                          <>
                            <div className="slot-admin-main">
                              <span className="slot-period">{slot.period}교시</span>
                              <div>
                                <strong>
                                  {slot.slot_type === "travel"
                                    ? `${slot.location_label} 순회`
                                    : `${slot.class_code} ${slot.subject}`}
                                </strong>
                                <div className="tiny">{slot.source_text}</div>
                              </div>
                            </div>
                            <div className="button-row compact">
                              <button className="button secondary" onClick={() => startEdit(slot)}>
                                수정
                              </button>
                              <button className="button warn" onClick={() => deleteSlot(slot)}>
                                삭제
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="slot-add-panel">
            <div>
              <h4>수업 추가</h4>
              <div className="panel-copy">정규 수업은 학반과 과목명을 입력하고, 순회는 학교명을 입력해 1교시 단위로 등록합니다.</div>
            </div>
            <AdminSlotForm draft={newSlotDraft} setDraft={setNewSlotDraft} submitLabel="수업 추가" onSubmit={createSlot} />
          </div>
        </div>
      )}
    </div>
  );
}

function AdminPanel({
  health,
  previewState,
  onPreviewFile,
  onCorrectionChange,
  onMissingTeacherActionChange,
  onConfirmPreview,
  calendarForm,
  setCalendarForm,
  onSaveCalendar,
  teachers,
  newTeacher,
  setNewTeacher,
  onCreateTeacher,
  onUpdateTeacher,
  onResetTeacher,
  onDeleteTeacher,
  adminTimetable,
  onCreateTimetableSlot,
  onUpdateTimetableSlot,
  onDeleteTimetableSlot,
  adminSwaps,
  onReloadAdminData,
  onCancelAcceptedSwap,
  onCancelAcceptedCoverage,
  onDeleteSwapRequest,
  onDeleteCoverageRequest,
  impactReport,
  onCheckImpact,
}) {
  const preview = previewState.preview;
  const missingTeachers = preview?.teacher_sync?.missing_teachers || [];
  const [teacherQuery, setTeacherQuery] = useState("");
  const [editingTeacherId, setEditingTeacherId] = useState(null);
  const [teacherDraft, setTeacherDraft] = useState({
    display_name: "",
    username: "",
    role: "teacher",
    schedule_label: "",
  });
  const [historyFilters, setHistoryFilters] = useState({
    query: "",
    classCode: "",
    date: "",
    status: "",
  });
  const [activeFilters, setActiveFilters] = useState({
    teacher: "",
    classCode: "",
    date: "",
    type: "",
    status: "",
    quick: "upcoming",
  });
  const [activeGroupBy, setActiveGroupBy] = useState("date");
  const [debugForm, setDebugForm] = useState({
    teacherId: "",
    date: today,
    period: "1",
  });
  const [debugReport, setDebugReport] = useState(null);
  const [debugError, setDebugError] = useState("");
  const [debugLoading, setDebugLoading] = useState(false);
  const [allowanceForm, setAllowanceForm] = useState({
    month: today.slice(0, 7),
    rate: "13000",
  });
  const [allowanceReport, setAllowanceReport] = useState(null);
  const [allowanceError, setAllowanceError] = useState("");
  const [allowanceLoading, setAllowanceLoading] = useState(false);
  const [adminSubTab, setAdminSubTab] = useState("manual");
  const adminSubTabs = [
    { id: "manual", label: "관리자 매뉴얼" },
    { id: "timetable", label: "시간표 업로드" },
    { id: "timetable-manage", label: "시간표 직접 관리" },
    { id: "members", label: "회원·교사 관리" },
    { id: "calendar", label: "학사일정" },
    { id: "debug", label: "시스템 점검" },
    { id: "impact", label: "영향도 검사" },
    { id: "allowance", label: "월별 보강 수당" },
    { id: "history", label: "교체·보강 이력" },
  ];
  useEffect(() => {
    if (!debugForm.teacherId && teachers.length) {
      const firstTeacher = teachers.find((teacher) => teacher.role === "teacher") || teachers[0];
      setDebugForm((current) => ({ ...current, teacherId: String(firstTeacher.id) }));
    }
  }, [debugForm.teacherId, teachers]);
  const filteredTeachers = teachers.filter((teacher) => {
    const keyword = teacherQuery.trim().toLowerCase();
    if (!keyword) return true;
    return [teacher.display_name, teacher.username, teacher.role, teacher.schedule_label]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword));
  });
  const rosterStats = {
    total: teachers.length,
    admins: teachers.filter((teacher) => teacher.role === "admin").length,
    teachers: teachers.filter((teacher) => teacher.role === "teacher").length,
    scheduled: teachers.filter((teacher) => teacher.slot_count > 0).length,
  };
  const activeAdminItems = adminSwaps?.active || [];
  const normalizeActiveItem = (item) => {
    const dates = item.dates?.length ? item.dates : [item.date, item.target_date, item.class_date].filter(Boolean);
    const classCodes = item.class_codes?.length
      ? item.class_codes
      : [item.source_class_code, item.target_class_code, item.class_code].filter(Boolean);
    const subjects = item.subjects?.length
      ? item.subjects
      : [item.source_subject, item.target_subject, item.subject].filter(Boolean);
    return {
      ...item,
      dates,
      classCodes,
      subjects,
      primaryDate: item.date || dates[0] || "",
      primaryPeriod: item.period || item.source_period || item.target_period || "",
      teacherNames: [item.requester_name, item.responder_name].filter(Boolean),
      searchText: [
        item.type_label,
        item.requester_name,
        item.responder_name,
        item.summary,
        item.status,
        ...dates,
        ...classCodes,
        ...subjects,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase(),
    };
  };
  const activeRows = activeAdminItems.map(normalizeActiveItem);
  const currentWeekStart = addDays(today, -((parseDateValue(today).getDay() + 6) % 7));
  const currentWeekEnd = addDays(currentWeekStart, 4);
  const activeTeacherCounts = activeRows.reduce((counts, item) => {
    item.teacherNames.forEach((name) => counts.set(name, (counts.get(name) || 0) + 1));
    return counts;
  }, new Map());
  const busyTeacherNames = new Set(
    [...activeTeacherCounts.entries()].filter(([, count]) => count >= 2).map(([name]) => name)
  );
  const sortedActiveRows = [...activeRows].sort((a, b) => {
    const aPast = a.primaryDate < today;
    const bPast = b.primaryDate < today;
    if (aPast !== bPast) return aPast ? 1 : -1;
    if (aPast && bPast) {
      const pastDateCompare = String(b.primaryDate).localeCompare(String(a.primaryDate));
      if (pastDateCompare) return pastDateCompare;
    } else {
      const dateCompare = String(a.primaryDate).localeCompare(String(b.primaryDate));
      if (dateCompare) return dateCompare;
    }
    return Number(a.primaryPeriod || 0) - Number(b.primaryPeriod || 0);
  });
  const filteredActiveRows = sortedActiveRows.filter((item) => {
    const teacherKeyword = activeFilters.teacher.trim().toLowerCase();
    const classKeyword = activeFilters.classCode.trim().toLowerCase();
    const matchesTeacher =
      !teacherKeyword || item.teacherNames.some((name) => String(name).toLowerCase().includes(teacherKeyword));
    const matchesClass =
      !classKeyword || item.classCodes.some((value) => String(value).toLowerCase().includes(classKeyword));
    const matchesDate = !activeFilters.date || item.dates.includes(activeFilters.date);
    const matchesType = !activeFilters.type || item.type === activeFilters.type;
    const matchesStatus = !activeFilters.status || item.status === activeFilters.status;
    const matchesQuick =
      activeFilters.quick === "week"
        ? item.primaryDate >= currentWeekStart && item.primaryDate <= currentWeekEnd
        : activeFilters.quick === "upcoming"
          ? item.primaryDate >= today
          : activeFilters.quick === "busy"
            ? item.teacherNames.some((name) => busyTeacherNames.has(name))
            : true;
    return matchesTeacher && matchesClass && matchesDate && matchesType && matchesStatus && matchesQuick;
  });
  const upcomingActiveRows = filteredActiveRows.filter((item) => item.primaryDate >= today);
  const pastActiveRows = filteredActiveRows.filter((item) => item.primaryDate < today);
  const groupActiveRows = (rows) =>
    rows.reduce((groups, item) => {
      const key = activeGroupBy === "teacher" ? item.requester_name || "미지정 교사" : item.primaryDate || "미지정 날짜";
      if (!groups[key]) groups[key] = [];
      groups[key].push(item);
      return groups;
    }, {});
  const activeFilterSummary = [
    activeFilters.quick === "week"
      ? "이번 주"
      : activeFilters.quick === "upcoming"
        ? "오늘 이후"
        : activeFilters.quick === "busy"
          ? "내역 많은 교사"
          : "전체",
    activeGroupBy === "teacher" ? "교사별 그룹" : "날짜별 그룹",
  ].join(" · ");
  const updateActiveFilter = (key, value) => {
    setActiveFilters((current) => ({ ...current, [key]: value }));
  };
  const adminHistoryItems = [
    ...(adminSwaps?.requests || []).map((request) => ({
      id: `swap-${request.id}`,
      type: "swap",
      typeLabel: "교체",
      requestId: request.id,
      status: request.status,
      requesterName: request.requester_name,
      responderName: request.responder_name,
      date: request.source_date,
      dates: [request.source_date, request.target_date],
      classCodes: [request.source_class_code, request.target_class_code],
      createdAt: request.created_at,
      respondedAt: request.responded_at,
      summary: `${request.source_date} ${request.source_period}교시 ${request.source_class_code} ${request.source_subject} ↔ ${request.target_date} ${request.target_period}교시 ${request.target_class_code} ${request.target_subject}`,
    })),
    ...(adminSwaps?.coverage_requests || []).map((request) => ({
      id: `coverage-${request.id}`,
      type: "coverage",
      typeLabel: "보강",
      requestId: request.id,
      status: request.status,
      requesterName: request.requester_name,
      responderName: request.responder_name,
      date: request.class_date,
      dates: [request.class_date],
      classCodes: [request.class_code],
      createdAt: request.created_at,
      respondedAt: request.responded_at,
      summary: `${request.class_date} ${request.day_label} ${request.period}교시 ${request.class_code} ${request.subject}`,
    })),
  ].sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
  const filteredAdminHistoryItems = adminHistoryItems.filter((item) => {
    const keyword = historyFilters.query.trim().toLowerCase();
    const classCode = historyFilters.classCode.trim().toLowerCase();
    const matchesKeyword =
      !keyword ||
      [item.typeLabel, item.requesterName, item.responderName, item.summary, item.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    const matchesClass =
      !classCode || item.classCodes.some((value) => String(value).toLowerCase().includes(classCode));
    const matchesDate = !historyFilters.date || item.dates.includes(historyFilters.date);
    const matchesStatus = !historyFilters.status || item.status === historyFilters.status;
    return matchesKeyword && matchesClass && matchesDate && matchesStatus;
  });
  const startTeacherEdit = (teacher) => {
    setEditingTeacherId(teacher.id);
    setTeacherDraft({
      display_name: teacher.display_name || "",
      username: teacher.username || "",
      role: teacher.role || "teacher",
      schedule_label: teacher.schedule_label || teacher.display_name || "",
    });
  };
  const saveTeacherEdit = async () => {
    await onUpdateTeacher(editingTeacherId, teacherDraft);
    setEditingTeacherId(null);
  };
  const runDebugCheck = async () => {
    if (!debugForm.teacherId || !debugForm.date || !debugForm.period) {
      setDebugError("교사, 날짜, 교시를 모두 선택해 주세요.");
      return;
    }
    setDebugLoading(true);
    setDebugError("");
    try {
      const payload = await apiFetch(
        `/api/admin/debug/schedule?teacher_id=${debugForm.teacherId}&date=${debugForm.date}&period=${debugForm.period}`,
      );
      setDebugReport(payload);
    } catch (error) {
      setDebugReport(null);
      setDebugError(extractErrorMessage(error));
    } finally {
      setDebugLoading(false);
    }
  };
  const runAllowanceCalculation = async () => {
    const rate = Number(allowanceForm.rate);
    if (!allowanceForm.month || Number.isNaN(rate) || rate < 0) {
      setAllowanceError("산출 월과 0원 이상의 보결 수당 단가를 입력해 주세요.");
      return;
    }
    setAllowanceLoading(true);
    setAllowanceError("");
    try {
      const payload = await apiFetch(
        `/api/admin/coverage-allowances?month=${allowanceForm.month}&rate=${Math.round(rate)}`,
      );
      setAllowanceReport(payload);
    } catch (error) {
      setAllowanceReport(null);
      setAllowanceError(extractErrorMessage(error));
    } finally {
      setAllowanceLoading(false);
    }
  };
  const downloadAllowanceCsv = () => {
    if (!allowanceReport) return;
    const rows = [
      ["월", "교사명", "ID", "보강건수", "단가", "지급액", "세부내역"],
      ...allowanceReport.teachers.map((teacher) => [
        allowanceReport.month,
        teacher.teacher_name,
        teacher.username,
        teacher.coverage_count,
        allowanceReport.rate,
        teacher.amount,
        teacher.details
          .map((detail) => `${detail.class_date} ${detail.period}교시 ${detail.class_code} ${detail.subject}`)
          .join(" / "),
      ]),
    ];
    const csv = rows
      .map((row) => row.map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `보강수당_${allowanceReport.month}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const renderActiveRow = (item) => (
    <details key={item.id} className={`active-history-row ${item.type}`}>
      <summary>
        <span className="active-date">
          <strong>{formatDateWithDay(item.primaryDate)}</strong>
          <small>{item.primaryPeriod}교시</small>
        </span>
        <span className={`mini-badge ${item.type === "coverage" ? "coverage-in" : "swapped-in"}`}>
          {item.type_label}
        </span>
        <span className="active-teachers">
          {item.requester_name} → {item.responder_name}
        </span>
        <span className="active-class-code">{item.classCodes.join(", ") || "-"}</span>
        <span className={`status-chip ${item.status}`}>{requestStatusLabel(item.status)}</span>
      </summary>
      <div className="active-row-detail">
        <div>
          <span>상세</span>
          <strong>{item.summary}</strong>
        </div>
        <div>
          <span>처리일시</span>
          <strong>{item.responded_at || item.created_at || "-"}</strong>
        </div>
        <button
          className="button warn"
          onClick={() =>
            item.type === "coverage" ? onCancelAcceptedCoverage(item.request_id) : onCancelAcceptedSwap(item.request_id)
          }
        >
          확정 취소
        </button>
      </div>
    </details>
  );
  const renderActiveGroups = (rows) => {
    const groups = groupActiveRows(rows);
    return Object.entries(groups).map(([key, items]) => (
      <div key={key} className="active-history-group">
        <div className="active-group-title">
          <strong>{activeGroupBy === "teacher" ? key : formatDateWithDay(key)}</strong>
          <span>{items.length}건</span>
        </div>
        <div className="active-history-list">{items.map(renderActiveRow)}</div>
      </div>
    ));
  };

  return (
    <div className="stack">
      <div className="panel admin-subnav-panel">
        <div className="panel-header">
          <div>
            <h3>관리자 기능</h3>
            <div className="panel-copy">필요한 관리 영역을 선택해서 집중적으로 확인합니다.</div>
          </div>
        </div>
        <div className="admin-subtabs" role="tablist" aria-label="관리자 하위 메뉴">
          {adminSubTabs.map((tab) => (
            <button
              key={tab.id}
              className={`admin-subtab ${adminSubTab === tab.id ? "active" : ""}`}
              type="button"
              role="tab"
              aria-selected={adminSubTab === tab.id}
              onClick={() => setAdminSubTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className={`panel admin-manual ${adminSubTab === "manual" ? "" : "is-hidden"}`}>
        <div className="manual-hero">
          <div>
            <span className="hero-pill">Admin Guide</span>
            <h3>처음 사용하는 관리자도 순서대로 따라오면 됩니다</h3>
            <p>
              학기 시작 전 기본 설정부터 시간표 확정, 교체·보강 운영, 계획서 출력까지 실제 업무 흐름에 맞춰
              정리했습니다.
            </p>
          </div>
          <div className="manual-quick-card">
            <strong>가장 중요한 원칙</strong>
            <span>시간표 파일은 업로드만으로 반영되지 않습니다.</span>
            <span>반드시 미리보기 확인 후 <b>시간표 확정</b>을 눌러야 실제 수업 데이터가 바뀝니다.</span>
          </div>
        </div>

        <div className="manual-section">
          <div className="panel-header">
            <div>
              <h3>1. 학기 시작 전 설정 순서</h3>
              <div className="panel-copy">새 학기 또는 시간표 개편 시 이 순서대로 처리하면 안전합니다.</div>
            </div>
          </div>
          <div className="manual-steps">
            <div className="manual-step">
              <span>01</span>
              <strong>학사일정 먼저 확인</strong>
              <p>학기 시작일·종료일을 입력하고, 공휴일·재량휴업일·개교기념일처럼 수업이 없는 날을 등록합니다.</p>
            </div>
            <div className="manual-step">
              <span>02</span>
              <strong>표준 양식으로 시간표 업로드</strong>
              <p>관리자 탭의 표준 양식을 내려받아 작성한 뒤 업로드합니다. 시트명, 열 개수, 요일/교시 구조가 다르면 거부됩니다.</p>
            </div>
            <div className="manual-step">
              <span>03</span>
              <strong>파싱 결과 미리보기 점검</strong>
              <p>교사 수, 수업 수, 순회 수업, 경고, 인식 실패 셀을 확인합니다. 실패 셀은 직접 수정하거나 비워서 제외할 수 있습니다.</p>
            </div>
            <div className="manual-step">
              <span>04</span>
              <strong>누락 교사 처리 선택</strong>
              <p>업로드 파일에 없는 기존 교사는 유지, 비활성화, 삭제 중 선택합니다. 기간제 종료·전입·전출 처리에 꼭 확인하세요.</p>
            </div>
            <div className="manual-step">
              <span>05</span>
              <strong>시간표 확정</strong>
              <p>확정을 누르면 교사 계정과 주간 시간표가 갱신됩니다. 대기 중인 교체·보강 요청은 운영 충돌 방지를 위해 자동 취소됩니다.</p>
            </div>
            <div className="manual-step">
              <span>06</span>
              <strong>영향도 검사 실행</strong>
              <p>재업로드나 학사일정 변경 후 확정된 교체·보강이 새 기준과 충돌하지 않는지 확인합니다.</p>
            </div>
          </div>
        </div>

        <div className="manual-grid">
          <div className="manual-card">
            <h4>시간표 업로드 체크</h4>
            <ul>
              <li>엑셀 파일은 표준 양식의 <b>주간시간표</b> 시트를 사용합니다.</li>
              <li>월~목은 1~7교시, 금요일은 1~6교시 구조입니다.</li>
              <li>빈 셀은 공강, 학교명(N시간)은 순회 수업 불가 시간으로 처리됩니다.</li>
              <li>홍길동 예시 행은 경고 후 제외됩니다.</li>
            </ul>
          </div>
          <div className="manual-card">
            <h4>교사 계정 관리</h4>
            <ul>
              <li>시간표에 새 교사가 있으면 계정이 자동 생성됩니다.</li>
              <li>기존 교사는 시간표 표시명 또는 로그인 ID 기준으로 매칭됩니다.</li>
              <li>비밀번호 초기화 시 환경설정의 초기 비밀번호가 적용됩니다.</li>
              <li>관리자 권한 부여, ID 수정, 표시명 수정은 회원·교사 관리에서 처리합니다.</li>
            </ul>
          </div>
          <div className="manual-card">
            <h4>교체·보강 운영</h4>
            <ul>
              <li>교체는 같은 주, 같은 학반, 양쪽 교사의 공강·순회 충돌 여부를 검사합니다.</li>
              <li>보강은 해당 날짜·교시에 수업이나 순회가 없는 교사를 후보로 표시합니다.</li>
              <li>대기 중인 요청이 걸린 교시는 잠금 처리되어 중복 요청을 막습니다.</li>
              <li>수락·거절·취소 내역은 알림과 이력에 남습니다.</li>
            </ul>
          </div>
          <div className="manual-card">
            <h4>이력 취소와 삭제</h4>
            <ul>
              <li>확정된 교체·보강은 먼저 <b>확정 취소</b>로 시간표 반영을 되돌립니다.</li>
              <li>취소·거절·만료된 이력은 필요 시 관리자 이력에서 삭제할 수 있습니다.</li>
              <li>개별 교사도 본인 관련 교체·보강 현황에서 취소 및 확인 후 삭제를 할 수 있습니다.</li>
              <li>보강 취소 시 상대 교사에게도 알림이 발송됩니다.</li>
            </ul>
          </div>
          <div className="manual-card">
            <h4>계획서 작성</h4>
            <ul>
              <li>계획서 작성 탭에서 날짜를 선택하면 해당 주의 내역을 조회합니다.</li>
              <li>일반 교사는 본인 관련 내역만, 관리자는 전체 내역을 확인할 수 있습니다.</li>
              <li>엑셀과 PDF 파일로 내려받아 결보강 계획서 작성에 활용합니다.</li>
              <li>주차와 날짜 범위를 확인한 뒤 제출용 파일을 내려받으세요.</li>
            </ul>
          </div>
          <div className="manual-card">
            <h4>문제가 생겼을 때</h4>
            <ul>
              <li>후보가 보이지 않으면 학사일정, 순회, 공강, 대기 요청 잠금을 먼저 확인합니다.</li>
              <li>업로드 후 교사가 사라진 것처럼 보이면 누락 교사 처리 선택을 확인합니다.</li>
              <li>시간표 직접 수정 후에는 영향도 검사를 실행해 확정 내역 충돌을 점검합니다.</li>
              <li>화면 상단 알림은 확인 버튼으로 닫을 수 있습니다.</li>
            </ul>
          </div>
        </div>

        <div className="manual-callout">
          <strong>운영 팁</strong>
          <span>
            학기 초에는 시간표 업로드 → 미리보기 → 누락 교사 처리 → 확정 → 영향도 검사 → 교사 로그인 안내 순서로
            진행하면 가장 안전합니다.
          </span>
        </div>
      </div>

      <div className={`admin-grid ${adminSubTab === "timetable" ? "" : "is-hidden"}`}>
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>시간표 업로드</h3>
              <div className="panel-copy">표준 양식 구조를 검증한 뒤, 미리보기 확인 후 확정합니다.</div>
            </div>
            <a className="button ghost" href="/api/template">
              표준 양식 다운로드
            </a>
          </div>
          <div className="field-grid">
            <input className="input" type="file" accept=".xlsx" onChange={onPreviewFile} />
            <div className="notice">
              템플릿 바깥쪽 메모 셀은 자동 무시되고, 인식 실패 셀은 아래에서 직접 보정할 수 있습니다.
            </div>
          </div>
        </div>

        <div className="panel">
          <h3>운영 메모</h3>
          <div className="stack">
            <div className="info-strip">기본 관리자 ID: {health?.default_admin_username || "admin"}</div>
            <div className="info-strip">계정 생성·초기화 시 환경설정의 초기 비밀번호가 적용됩니다.</div>
            <div className="info-strip">최초 로그인 시 비밀번호 변경이 강제됩니다.</div>
          </div>
        </div>
      </div>

      <div className={`panel ${adminSubTab === "debug" ? "" : "is-hidden"}`}>
        <div className="panel-header">
          <div>
            <h3>시스템 점검</h3>
            <div className="panel-copy">
              특정 교사·날짜·교시를 기준으로 수업 상태, 잠금 사유, 후보 API 결과를 한 번에 확인합니다.
            </div>
          </div>
          <button className="button primary" onClick={runDebugCheck} disabled={debugLoading}>
            {debugLoading ? "점검 중..." : "점검 실행"}
          </button>
        </div>
        <div className="debug-form">
          <label className="field">
            <span className="field-title">교사</span>
            <select
              className="select"
              value={debugForm.teacherId}
              onChange={(event) => setDebugForm((current) => ({ ...current, teacherId: event.target.value }))}
            >
              {teachers.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {teacher.display_name} · {teacher.role}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-title">날짜</span>
            <input
              className="input"
              type="date"
              value={debugForm.date}
              onChange={(event) => setDebugForm((current) => ({ ...current, date: event.target.value }))}
            />
          </label>
          <label className="field">
            <span className="field-title">교시</span>
            <select
              className="select"
              value={debugForm.period}
              onChange={(event) => setDebugForm((current) => ({ ...current, period: event.target.value }))}
            >
              {[1, 2, 3, 4, 5, 6, 7].map((period) => (
                <option key={period} value={period}>
                  {period}교시
                </option>
              ))}
            </select>
          </label>
        </div>
        {debugError ? <div className="status error">{debugError}</div> : null}
        {!debugReport ? (
          <div className="empty">점검할 교사와 날짜, 교시를 선택한 뒤 점검 실행을 눌러 주세요.</div>
        ) : (
          <div className="debug-grid">
            <div className="debug-card emphasis">
              <span>현재 셀</span>
              <strong>{prettySlot(debugReport.selected_cell)}</strong>
              <small>
                {debugReport.teacher.display_name} · {formatDateWithDay(debugReport.date)} · {debugReport.period}교시 ·{" "}
                {statusTextForCell(debugReport.selected_cell)}
              </small>
            </div>
            <div className="debug-card">
              <span>학사일정</span>
              <strong>{debugReport.day.is_school_day ? "수업일" : "수업 없음"}</strong>
              <small>
                {debugReport.day.day_label}요일 · {debugReport.day.kind}
                {debugReport.day.label ? ` · ${debugReport.day.label}` : ""}
              </small>
            </div>
            <div className="debug-card wide">
              <span>진단 메시지</span>
              <div className="debug-chip-list">
                {debugReport.issues.map((issue, index) => (
                  <span key={index} className={`debug-chip ${issue.level}`}>
                    {issue.message}
                  </span>
                ))}
              </div>
            </div>
            <div className="debug-card wide">
              <span>교체·보강 잠금</span>
              {debugReport.locks.swaps.length || debugReport.locks.coverage.length ? (
                <div className="debug-lock-list">
                  {[...debugReport.locks.swaps, ...debugReport.locks.coverage].map((lock) => (
                    <div key={`${lock.type}-${lock.id}`} className={`debug-lock ${lock.type}`}>
                      <strong>
                        {lock.type === "swap" ? "교체" : "보강"} #{lock.id} · {requestStatusLabel(lock.status)}
                      </strong>
                      <small>{lock.message}</small>
                    </div>
                  ))}
                </div>
              ) : (
                <small>현재 선택 교시에 걸린 대기/확정 잠금이 없습니다.</small>
              )}
            </div>
            <div className="debug-card wide">
              <span>API 점검</span>
              <div className="debug-api-list">
                {debugReport.api_checks.map((check) => (
                  <div key={check.label} className={`debug-api ${check.ok ? "ok" : "error"}`}>
                    <strong>{check.label}</strong>
                    <small>
                      {check.ok
                        ? [
                            check.candidate_count !== undefined ? `후보 ${check.candidate_count}건` : null,
                            check.available_count !== undefined ? `가능 ${check.available_count}명` : null,
                            check.busy_count !== undefined ? `수업 중 ${check.busy_count}명` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")
                        : check.error}
                    </small>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className={`panel ${adminSubTab === "impact" ? "" : "is-hidden"}`}>
        <div className="panel-header">
          <div>
            <h3>확정 교체·보강 영향도 검사</h3>
            <div className="panel-copy">
              시간표 재업로드나 학사일정 변경 뒤, 현재 확정 내역이 새 기준과 충돌하는지 점검합니다.
            </div>
          </div>
          <button className="button primary" onClick={onCheckImpact}>
            영향도 검사
          </button>
        </div>
        {!impactReport ? (
          <div className="empty">검사 버튼을 누르면 확정된 교체·보강의 위험 요소를 확인합니다.</div>
        ) : (
          <div className="stack">
            <div className="plan-summary">
              <div className="roster-metric">
                <span>교체</span>
                <strong>{impactReport.summary.accepted_swap_count}</strong>
              </div>
              <div className="roster-metric">
                <span>보강</span>
                <strong>{impactReport.summary.accepted_coverage_count}</strong>
              </div>
              <div className="roster-metric">
                <span>오류</span>
                <strong>{impactReport.summary.error_count}</strong>
              </div>
              <div className="roster-metric">
                <span>주의</span>
                <strong>{impactReport.summary.warning_count}</strong>
              </div>
            </div>
            {!impactReport.issues.length ? (
              <div className="info-strip">현재 확정된 교체·보강에서 감지된 충돌이 없습니다.</div>
            ) : (
              <div className="tableish">
                {impactReport.issues.map((issue, index) => (
                  <div
                    key={`${issue.type}-${issue.request_id}-${index}`}
                    className={`request-card ${issue.severity === "error" ? "cancelled" : "pending"}`}
                  >
                    <div className="panel-header">
                      <div>
                        <strong>
                          {issue.type_label} · {issue.requester_name} → {issue.responder_name}
                        </strong>
                        <div className="panel-copy">{issue.summary}</div>
                      </div>
                      <span className={`status-chip ${issue.severity === "error" ? "cancelled" : "pending"}`}>
                        {issue.severity === "error" ? "오류" : "주의"}
                      </span>
                    </div>
                    <div className="tiny">{issue.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className={`panel ${adminSubTab === "allowance" ? "" : "is-hidden"}`}>
        <div className="panel-header">
          <div>
            <h3>월별 보강 수당 산출</h3>
            <div className="panel-copy">
              선택 월에 수락 완료된 보강만 집계하고, 보강 담당 교사 기준으로 수당을 계산합니다.
            </div>
          </div>
          <div className="button-row">
            <button className="button primary" onClick={runAllowanceCalculation} disabled={allowanceLoading}>
              {allowanceLoading ? "산출 중..." : "수당 산출"}
            </button>
            <button className="button secondary" onClick={downloadAllowanceCsv} disabled={!allowanceReport}>
              CSV 다운로드
            </button>
          </div>
        </div>
        <div className="allowance-form">
          <label className="field">
            <span className="field-title">산출 월</span>
            <input
              className="input"
              type="month"
              value={allowanceForm.month}
              onChange={(event) => setAllowanceForm((current) => ({ ...current, month: event.target.value }))}
            />
          </label>
          <label className="field">
            <span className="field-title">보결 수당 단가</span>
            <input
              className="input"
              type="number"
              min="0"
              step="100"
              value={allowanceForm.rate}
              onChange={(event) => setAllowanceForm((current) => ({ ...current, rate: event.target.value }))}
              placeholder="예: 13000"
            />
          </label>
          <div className="notice">
            대기·거절·취소·만료 보강과 단순 교체는 수당 산정에서 제외됩니다.
          </div>
        </div>
        {allowanceError ? <div className="status error">{allowanceError}</div> : null}
        {!allowanceReport ? (
          <div className="empty">월과 단가를 입력한 뒤 수당 산출을 눌러 주세요.</div>
        ) : (
          <div className="stack">
            <div className="plan-summary">
              <div className="roster-metric">
                <span>산출 기간</span>
                <strong>{allowanceReport.month}</strong>
              </div>
              <div className="roster-metric">
                <span>대상 교사</span>
                <strong>{allowanceReport.summary.teacher_count}</strong>
              </div>
              <div className="roster-metric">
                <span>보강 건수</span>
                <strong>{allowanceReport.summary.coverage_count}</strong>
              </div>
              <div className="roster-metric highlight">
                <span>총 지급액</span>
                <strong>{formatCurrency(allowanceReport.summary.total_amount)}</strong>
              </div>
            </div>
            {!allowanceReport.teachers.length ? (
              <div className="empty">해당 월에 수락 완료된 보강 내역이 없습니다.</div>
            ) : (
              <div className="allowance-list">
                {allowanceReport.teachers.map((teacher) => {
                  const uniqueDates = [...new Set(teacher.details.map((detail) => detail.class_date))];
                  const visibleDates = uniqueDates.slice(0, 5);
                  const hiddenDateCount = Math.max(uniqueDates.length - visibleDates.length, 0);
                  return (
                    <details key={teacher.teacher_id} className="allowance-row">
                      <summary>
                        <span className="allowance-teacher-cell">
                          <strong>{teacher.teacher_name}</strong>
                          <small>{teacher.username}</small>
                          <span className="allowance-date-strip">
                            {visibleDates.map((dateValue) => (
                              <em key={dateValue}>{formatDateWithDay(dateValue)}</em>
                            ))}
                            {hiddenDateCount ? <em>+{hiddenDateCount}일</em> : null}
                          </span>
                        </span>
                        <span className="allowance-count-cell">
                          <strong>{teacher.coverage_count}건</strong>
                          <small>{uniqueDates.length}일</small>
                        </span>
                        <strong>{formatCurrency(teacher.amount)}</strong>
                      </summary>
                      <div className="allowance-detail-list">
                        <div className="allowance-detail allowance-detail-head">
                          <span>일자</span>
                          <span>교시</span>
                          <span>보강 수업</span>
                          <span>원 담당</span>
                          <span>승인일</span>
                        </div>
                        {teacher.details.map((detail) => (
                          <div key={detail.id} className="allowance-detail">
                            <span>{formatDateWithDay(detail.class_date)}</span>
                            <strong>{detail.period}교시</strong>
                            <strong>
                              {detail.class_code} {detail.subject}
                            </strong>
                            <small>{detail.requester_name}</small>
                            <small>{detail.responded_at ? detail.responded_at.slice(0, 10) : "-"}</small>
                          </div>
                        ))}
                      </div>
                    </details>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {preview ? (
        <div className={`panel ${adminSubTab === "timetable" ? "" : "is-hidden"}`}>
          <div className="panel-header">
            <div>
              <h3>파싱 결과 미리보기</h3>
              <div className="panel-copy">
                교사 {preview.summary.teacher_count}명 · 정규수업 {preview.summary.class_slot_count}건 · 순회{" "}
                {preview.summary.travel_slot_count}건
              </div>
            </div>
            <button className="button primary" onClick={onConfirmPreview}>
              시간표 확정
            </button>
          </div>

          {preview.warnings?.length ? (
            <div className="tableish" style={{ marginBottom: "14px" }}>
              {preview.warnings.map((warning, index) => (
                <div key={index} className="preview-card">
                  {warning}
                </div>
              ))}
            </div>
          ) : null}

          {missingTeachers.length ? (
            <div className="stack" style={{ marginBottom: "14px" }}>
              <div className="notice">
                이번 업로드 파일에 없는 기존 교사가 {missingTeachers.length}명 있습니다. 기간제 종료, 전입·전출,
                휴직 등 상황에 맞게 처리 방식을 선택하세요.
              </div>
              <div className="tableish">
                {missingTeachers.map((teacher) => (
                  <div key={teacher.id} className="preview-card">
                    <div className="panel-header">
                      <div>
                        <strong>{teacher.display_name}</strong>
                        <div className="panel-copy">
                          {teacher.username} · {teacher.schedule_label || "시간표 라벨 없음"} · 기존 수업{" "}
                          {teacher.slot_count}건
                        </div>
                      </div>
                      <select
                        className="select"
                        style={{ maxWidth: "180px" }}
                        value={previewState.missingTeacherActions?.[teacher.id] || "keep"}
                        onChange={(event) => onMissingTeacherActionChange(teacher.id, event.target.value)}
                      >
                        <option value="keep">유지</option>
                        <option value="deactivate">비활성화</option>
                        <option value="delete">삭제</option>
                      </select>
                    </div>
                    <div className="tiny">
                      유지: 계정은 계속 사용 가능 · 비활성화: 로그인 차단, 같은 교사가 다시 업로드되면 재활성화 ·
                      삭제: 계정을 숨기고 다음 업로드 시 새 계정 생성
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : preview.teacher_sync ? (
            <div className="info-strip" style={{ marginBottom: "14px" }}>
              이번 업로드 기준으로 누락된 기존 교사가 없습니다.
            </div>
          ) : null}

          {preview.failed_cells?.length ? (
            <div className="stack">
              <h4>인식 실패 셀 수동 보정</h4>
              {preview.failed_cells.map((cell) => (
                <div key={cell.cell_ref} className="preview-card">
                  <div className="panel-header">
                    <div>
                      <strong>
                        {cell.cell_ref} · {cell.teacher_name} · {cell.day_label} {cell.period}교시
                      </strong>
                      <div className="panel-copy">
                        원본값: {cell.value} / {cell.reason}
                      </div>
                    </div>
                    <button className="button ghost" onClick={() => onCorrectionChange(cell.cell_ref, "")}>
                      비워서 제외
                    </button>
                  </div>
                  <input
                    className="input"
                    placeholder="예: 중1 국어 또는 다인중학교(2시간)"
                    value={previewState.corrections[cell.cell_ref] ?? ""}
                    onChange={(event) => onCorrectionChange(cell.cell_ref, event.target.value)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="info-strip">모든 셀이 정상 인식되었습니다. 바로 확정할 수 있습니다.</div>
          )}
        </div>
      ) : null}

      <div className={adminSubTab === "timetable-manage" ? "" : "is-hidden"}>
        <AdminTimetableManager
          teachers={teachers}
          slots={adminTimetable?.slots || []}
          onCreateSlot={onCreateTimetableSlot}
          onUpdateSlot={onUpdateTimetableSlot}
          onDeleteSlot={onDeleteTimetableSlot}
        />
      </div>

      <div
        className={`admin-grid admin-single ${
          adminSubTab === "calendar" || adminSubTab === "members" ? "" : "is-hidden"
        }`}
      >
        <div className={`panel ${adminSubTab === "calendar" ? "" : "is-hidden"}`}>
          <div className="panel-header">
            <div>
              <h3>학사일정</h3>
              <div className="panel-copy">학기 범위를 지정하고 공휴일·휴업일을 직접 관리합니다.</div>
            </div>
            <button className="button primary" onClick={onSaveCalendar}>
              일정 저장
            </button>
          </div>
          <div className="two-up">
            <div className="field">
              <span className="field-title">학기 시작일</span>
              <input
                className="input"
                type="date"
                value={calendarForm.semester_start}
                onChange={(event) => setCalendarForm((prev) => ({ ...prev, semester_start: event.target.value }))}
              />
            </div>
            <div className="field">
              <span className="field-title">학기 종료일</span>
              <input
                className="input"
                type="date"
                value={calendarForm.semester_end}
                onChange={(event) => setCalendarForm((prev) => ({ ...prev, semester_end: event.target.value }))}
              />
            </div>
          </div>
          <div className="divider"></div>
          <div className="panel-header">
            <h4>특별 휴업일</h4>
            <button
              className="button ghost"
              onClick={() =>
                setCalendarForm((prev) => ({
                  ...prev,
                  special_days: [...prev.special_days, { date: "", label: "", kind: "holiday" }],
                }))
              }
            >
              날짜 추가
            </button>
          </div>
          <div className="special-day-list">
            {calendarForm.special_days.map((item, index) => (
              <div key={index} className="special-day-card">
                <div className="inline-form">
                  <input
                    className="input"
                    type="date"
                    value={item.date}
                    onChange={(event) =>
                      setCalendarForm((prev) => {
                        const next = [...prev.special_days];
                        next[index] = { ...next[index], date: event.target.value };
                        return { ...prev, special_days: next };
                      })
                    }
                  />
                  <input
                    className="input"
                    type="text"
                    placeholder="예: 개교기념일"
                    value={item.label}
                    onChange={(event) =>
                      setCalendarForm((prev) => {
                        const next = [...prev.special_days];
                        next[index] = { ...next[index], label: event.target.value };
                        return { ...prev, special_days: next };
                      })
                    }
                  />
                  <select
                    className="select"
                    value={item.kind}
                    onChange={(event) =>
                      setCalendarForm((prev) => {
                        const next = [...prev.special_days];
                        next[index] = { ...next[index], kind: event.target.value };
                        return { ...prev, special_days: next };
                      })
                    }
                  >
                    <option value="holiday">holiday</option>
                    <option value="closure">closure</option>
                  </select>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className={`panel ${adminSubTab === "members" ? "" : "is-hidden"}`}>
          <div className="panel-header">
            <div>
              <h3>회원·교사 관리</h3>
              <div className="panel-copy">시간표 업로드와 수동 생성으로 등록된 계정을 한곳에서 조회·수정합니다.</div>
            </div>
            <input
              className="input"
              style={{ maxWidth: "240px" }}
              type="text"
              placeholder="이름, ID, 권한 검색"
              value={teacherQuery}
              onChange={(event) => setTeacherQuery(event.target.value)}
            />
          </div>
          <div className="roster-metrics">
            <div className="roster-metric">
              <span>전체</span>
              <strong>{rosterStats.total}</strong>
            </div>
            <div className="roster-metric">
              <span>관리자</span>
              <strong>{rosterStats.admins}</strong>
            </div>
            <div className="roster-metric">
              <span>교사</span>
              <strong>{rosterStats.teachers}</strong>
            </div>
            <div className="roster-metric">
              <span>시간표 배정</span>
              <strong>{rosterStats.scheduled}</strong>
            </div>
          </div>
          <div className="stack">
            <div className="inline-form">
              <input
                className="input"
                type="text"
                placeholder="표시 이름"
                value={newTeacher.display_name}
                onChange={(event) => setNewTeacher((prev) => ({ ...prev, display_name: event.target.value }))}
              />
              <input
                className="input"
                type="text"
                placeholder="로그인 ID"
                value={newTeacher.username}
                onChange={(event) => setNewTeacher((prev) => ({ ...prev, username: event.target.value }))}
              />
              <select
                className="select"
                value={newTeacher.role}
                onChange={(event) => setNewTeacher((prev) => ({ ...prev, role: event.target.value }))}
              >
                <option value="teacher">teacher</option>
                <option value="admin">admin</option>
              </select>
              <button className="button primary" onClick={onCreateTeacher}>
                계정 생성
              </button>
            </div>
            <div className="tableish member-list">
              {filteredTeachers.map((teacher) => (
                <div key={teacher.id} className="list-card member-card">
                  <div className="panel-header member-card-top">
                    <div>
                      <strong>{teacher.display_name}</strong>
                      <div className="tiny">
                        {teacher.username} · {teacher.role} · 수업 {teacher.class_slot_count}건 · 순회 {teacher.travel_slot_count}건
                      </div>
                    </div>
                    <span className={`chip ${teacher.must_change_password ? "warning" : "success"}`}>
                      {teacher.must_change_password ? "비밀번호 변경 필요" : "활성"}
                    </span>
                  </div>
                  {editingTeacherId === teacher.id ? (
                    <div className="member-edit-form">
                      <input
                        className="input"
                        type="text"
                        placeholder="표시 이름"
                        value={teacherDraft.display_name}
                        onChange={(event) =>
                          setTeacherDraft((prev) => ({ ...prev, display_name: event.target.value }))
                        }
                      />
                      <input
                        className="input"
                        type="text"
                        placeholder="로그인 ID"
                        value={teacherDraft.username}
                        onChange={(event) => setTeacherDraft((prev) => ({ ...prev, username: event.target.value }))}
                      />
                      <input
                        className="input"
                        type="text"
                        placeholder="시간표 표시명"
                        value={teacherDraft.schedule_label}
                        onChange={(event) =>
                          setTeacherDraft((prev) => ({ ...prev, schedule_label: event.target.value }))
                        }
                      />
                      <select
                        className="select"
                        value={teacherDraft.role}
                        onChange={(event) => setTeacherDraft((prev) => ({ ...prev, role: event.target.value }))}
                      >
                        <option value="teacher">teacher</option>
                        <option value="admin">admin</option>
                      </select>
                    </div>
                  ) : null}
                  <div className="button-row member-actions">
                    {editingTeacherId === teacher.id ? (
                      <>
                        <button className="button primary" onClick={saveTeacherEdit}>
                          저장
                        </button>
                        <button className="button ghost" onClick={() => setEditingTeacherId(null)}>
                          취소
                        </button>
                      </>
                    ) : (
                      <button className="button secondary" onClick={() => startTeacherEdit(teacher)}>
                        수정
                      </button>
                    )}
                    <button className="button reset" onClick={() => onResetTeacher(teacher.id)}>
                      비밀번호 초기화
                    </button>
                    <button className="button warn" onClick={() => onDeleteTeacher(teacher.id)}>
                      삭제
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className={`panel ${adminSubTab === "history" ? "" : "is-hidden"}`}>
        <div className="panel-header">
          <div>
            <h3>현재 반영 중인 교체·보강</h3>
            <div className="panel-copy">
              필터와 그룹을 조합해 현재 시간표에 반영된 내역을 빠르게 찾습니다. 상세를 펼치면 취소할 수 있습니다.
            </div>
          </div>
          <button className="button secondary" onClick={onReloadAdminData}>
            이력 새로고침
          </button>
        </div>
        {!activeAdminItems.length ? (
          <div className="empty">현재 반영 중인 교체·보강 내역이 없습니다.</div>
        ) : (
          <div className="active-history-board">
            <div className="active-summary-strip">
              <span className="chip accent">{activeFilterSummary}</span>
              <span className="chip success">조회 {filteredActiveRows.length}건</span>
              <span className="chip">전체 {activeAdminItems.length}건</span>
              {pastActiveRows.length ? <span className="chip warning">지난 내역 {pastActiveRows.length}건</span> : null}
            </div>
            <div className="active-filter-grid">
              <label className="field">
                <span className="field-title">교사명</span>
                <input
                  className="input"
                  placeholder="교사 이름"
                  value={activeFilters.teacher}
                  onChange={(event) => updateActiveFilter("teacher", event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field-title">학반</span>
                <input
                  className="input"
                  placeholder="예: 303"
                  value={activeFilters.classCode}
                  onChange={(event) => updateActiveFilter("classCode", event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field-title">날짜</span>
                <input
                  className="input"
                  type="date"
                  value={activeFilters.date}
                  onChange={(event) => updateActiveFilter("date", event.target.value)}
                />
              </label>
              <label className="field">
                <span className="field-title">유형</span>
                <select
                  className="input"
                  value={activeFilters.type}
                  onChange={(event) => updateActiveFilter("type", event.target.value)}
                >
                  <option value="">전체</option>
                  <option value="swap">교체</option>
                  <option value="coverage">보강</option>
                </select>
              </label>
              <label className="field">
                <span className="field-title">상태</span>
                <select
                  className="input"
                  value={activeFilters.status}
                  onChange={(event) => updateActiveFilter("status", event.target.value)}
                >
                  <option value="">전체</option>
                  <option value="accepted">반영 중</option>
                </select>
              </label>
            </div>
            <div className="active-toolbar">
              <div className="quick-filter-row" aria-label="빠른 필터">
                {[
                  ["week", "이번 주만 보기"],
                  ["upcoming", "오늘 이후만 보기"],
                  ["busy", "내역 많은 교사만 보기"],
                  ["all", "전체 보기"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    className={`filter-chip ${activeFilters.quick === value ? "active" : ""}`}
                    onClick={() => updateActiveFilter("quick", value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="segmented-control" aria-label="그룹 방식">
                <button
                  type="button"
                  className={activeGroupBy === "date" ? "active" : ""}
                  onClick={() => setActiveGroupBy("date")}
                >
                  날짜별 그룹
                </button>
                <button
                  type="button"
                  className={activeGroupBy === "teacher" ? "active" : ""}
                  onClick={() => setActiveGroupBy("teacher")}
                >
                  교사별 그룹
                </button>
              </div>
            </div>
            {!filteredActiveRows.length ? (
              <div className="empty">조건에 맞는 반영 내역이 없습니다.</div>
            ) : (
              <div className="active-history-sections">
                {upcomingActiveRows.length ? (
                  <section>
                    <div className="section-kicker">다가오는 내역</div>
                    {renderActiveGroups(upcomingActiveRows)}
                  </section>
                ) : null}
                {pastActiveRows.length ? (
                  <details className="past-active-section" open={activeFilters.quick === "all"}>
                    <summary>지난 내역 {pastActiveRows.length}건 보기</summary>
                    {renderActiveGroups(pastActiveRows)}
                  </details>
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>

      <div className={`panel ${adminSubTab === "history" ? "" : "is-hidden"}`}>
        <div className="panel-header">
          <div>
            <h3>전체 교체·보강 이력</h3>
            <div className="panel-copy">처리 완료된 요청은 삭제할 수 있고, 확정 상태는 먼저 취소해야 삭제됩니다.</div>
          </div>
        </div>
        <div className="field-grid history-filter-grid">
          <input
            className="input"
            type="text"
            placeholder="교사명, 내용 검색"
            value={historyFilters.query}
            onChange={(event) => setHistoryFilters((prev) => ({ ...prev, query: event.target.value }))}
          />
          <input
            className="input"
            type="text"
            placeholder="학반"
            value={historyFilters.classCode}
            onChange={(event) => setHistoryFilters((prev) => ({ ...prev, classCode: event.target.value }))}
          />
          <input
            className="input"
            type="date"
            value={historyFilters.date}
            onChange={(event) => setHistoryFilters((prev) => ({ ...prev, date: event.target.value }))}
          />
          <select
            className="select"
            value={historyFilters.status}
            onChange={(event) => setHistoryFilters((prev) => ({ ...prev, status: event.target.value }))}
          >
            <option value="">전체 상태</option>
            <option value="pending">pending</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="expired">expired</option>
            <option value="cancelled">cancelled</option>
          </select>
          <button
            className="button ghost"
            onClick={() => setHistoryFilters({ query: "", classCode: "", date: "", status: "" })}
          >
            필터 초기화
          </button>
        </div>
        {!adminHistoryItems.length ? (
          <div className="empty">아직 교체·보강 이력이 없습니다.</div>
        ) : !filteredAdminHistoryItems.length ? (
          <div className="empty">조건에 맞는 이력이 없습니다.</div>
        ) : (
          <div className="tableish">
            {filteredAdminHistoryItems.map((item) => (
              <div key={item.id} className={`request-card ${item.status}`}>
                <div className="panel-header">
                  <div>
                    <strong>
                      {item.typeLabel} · {item.requesterName} → {item.responderName}
                    </strong>
                    <div className="panel-copy">{item.summary}</div>
                  </div>
                  <span className={`status-chip ${item.status}`}>{item.status}</span>
                </div>
                <div className="chip-row">
                  <span className="chip">요청 {item.createdAt || "-"}</span>
                  <span className="chip">처리 {item.respondedAt || "대기 중"}</span>
                </div>
                <div className="button-row" style={{ marginTop: "12px" }}>
                  {item.status === "accepted" ? (
                    <button
                      className="button warn"
                      onClick={() =>
                        item.type === "coverage"
                          ? onCancelAcceptedCoverage(item.requestId)
                          : onCancelAcceptedSwap(item.requestId)
                      }
                    >
                      확정 취소
                    </button>
                  ) : (
                    <button
                      className="button warn"
                      onClick={() =>
                        item.type === "coverage"
                          ? onDeleteCoverageRequest(item.requestId)
                          : onDeleteSwapRequest(item.requestId)
                      }
                    >
                      이력 삭제
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function App() {
  const [bootStatus, setBootStatus] = useState("초기 상태를 확인하는 중입니다.");
  const [statusTone, setStatusTone] = useState("info");
  const [health, setHealth] = useState(null);
  const [user, setUser] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const pendingTabScrollRef = useRef(null);

  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });

  const [weekly, setWeekly] = useState(null);
  const [weeklyDate, setWeeklyDate] = useState(today);
  const [daySchedule, setDaySchedule] = useState(null);
  const [swapDate, setSwapDate] = useState(today);
  const [sourceChoice, setSourceChoice] = useState(null);
  const [candidateWeekOffset, setCandidateWeekOffset] = useState(0);
  const [candidateResults, setCandidateResults] = useState({ 0: null, 1: null });
  const [coverageDate, setCoverageDate] = useState(today);
  const [coverageSources, setCoverageSources] = useState(null);
  const [coverageSourceChoice, setCoverageSourceChoice] = useState(null);
  const [coverageCandidateWeekOffset, setCoverageCandidateWeekOffset] = useState(0);
  const [coverageCandidateTab, setCoverageCandidateTab] = useState("available");
  const [coverageCandidateResults, setCoverageCandidateResults] = useState({ 0: null, 1: null });
  const [swapRequests, setSwapRequests] = useState({ received: [], sent: [] });
  const [coverageRequests, setCoverageRequests] = useState({ received: [], sent: [] });
  const [notifications, setNotifications] = useState({ items: [] });
  const [planDate, setPlanDate] = useState(today);
  const [weeklyPlan, setWeeklyPlan] = useState(null);

  const [calendarForm, setCalendarForm] = useState({
    semester_start: "",
    semester_end: "",
    special_days: [],
  });
  const [teachers, setTeachers] = useState([]);
  const [newTeacher, setNewTeacher] = useState({ display_name: "", username: "", role: "teacher" });
  const [adminTimetable, setAdminTimetable] = useState({ slots: [] });
  const [adminSwaps, setAdminSwaps] = useState({ requests: [], history: [] });
  const [impactReport, setImpactReport] = useState(null);
  const [previewState, setPreviewState] = useState({
    previewId: null,
    preview: null,
    corrections: {},
    missingTeacherActions: {},
  });

  const unreadCount = useMemo(
    () => (notifications.items || []).filter((item) => !item.is_read).length,
    [notifications],
  );
  const isAdmin = user?.role === "admin";
  const weeklyMeta = useMemo(() => getWeeklyMeta(weeklyDate, weekly), [weeklyDate, weekly]);
  const candidateResult = candidateResults[candidateWeekOffset];
  const hasCandidateSearch = Boolean(candidateResults[0] || candidateResults[1]);
  const coverageResult = coverageCandidateResults[coverageCandidateWeekOffset];
  const hasCoverageCandidateSearch = Boolean(coverageCandidateResults[0] || coverageCandidateResults[1]);

  const scrollToTabPanel = (tabId) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const target = document.querySelector(`[data-tab-panel="${tabId}"]`) || document.querySelector(".content");
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  };

  const changeTab = (tabId) => {
    pendingTabScrollRef.current = tabId;
    setActiveTab(tabId);
    if (tabId === activeTab) {
      scrollToTabPanel(tabId);
    }
  };

  const loadHealth = async () => {
    try {
      const payload = await apiFetch("/api/health");
      setHealth(payload);
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const loadCommonData = async (sessionUser, weekDate = weeklyDate) => {
    if (sessionUser.role === "admin") {
      setWeekly(null);
      setSwapRequests({ received: [], sent: [] });
      setCoverageRequests({ received: [], sent: [] });
      setNotifications({ items: [] });
      await loadAdminData();
      return;
    }

    const tasks = [
      apiFetch(`/api/schedule/weekly?date=${weekDate}`),
      apiFetch("/api/swaps/requests"),
      apiFetch("/api/coverage/requests"),
      apiFetch("/api/notifications"),
    ];
    const [weeklyPayload, requestsPayload, coverageRequestsPayload, notificationPayload] = await Promise.all(tasks);
    setWeekly(weeklyPayload);
    setSwapRequests(requestsPayload);
    setCoverageRequests(coverageRequestsPayload);
    setNotifications(notificationPayload);
  };

  const loadAdminData = async () => {
    const [calendarPayload, teacherPayload, timetablePayload, swapAdminPayload] = await Promise.all([
      apiFetch("/api/admin/calendar-settings"),
      apiFetch("/api/admin/teachers"),
      apiFetch("/api/admin/timetable/slots"),
      apiFetch("/api/admin/swaps"),
    ]);
    setCalendarForm(calendarPayload);
    setTeachers(teacherPayload.teachers || []);
    setAdminTimetable(timetablePayload);
    setAdminSwaps(swapAdminPayload);
  };

  const loadWeeklyPlan = async (dateValue = planDate) => {
    const payload = await apiFetch(`/api/plans/weekly?date=${dateValue}`);
    setWeeklyPlan(payload);
  };

  const bootstrapSession = async () => {
    try {
      await loadHealth();
      const payload = await apiFetch("/api/me");
      setUser(payload.user);
      setActiveTab(payload.user.role === "admin" ? "admin" : "dashboard");
      setBootStatus("");
      setStatusTone("info");
      if (!payload.user.must_change_password) {
        await loadCommonData(payload.user);
        await loadWeeklyPlan();
      }
    } catch (error) {
      setUser(null);
      setBootStatus(typeof error?.detail === "string" ? "" : extractErrorMessage(error));
    }
  };

  useEffect(() => {
    bootstrapSession();
  }, []);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    loadCommonData(user, weeklyDate).catch((error) => {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    });
  }, [weeklyDate]);

  useEffect(() => {
    if (!user || user.must_change_password || !planDate) return;
    loadWeeklyPlan(planDate).catch((error) => {
      setWeeklyPlan(null);
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    });
  }, [planDate, user?.id, user?.must_change_password]);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    if (pendingTabScrollRef.current !== activeTab) return;
    pendingTabScrollRef.current = null;
    scrollToTabPanel(activeTab);
  }, [activeTab, user?.id, user?.must_change_password]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || activeTab !== "admin") return;
    loadAdminData().catch((error) => {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    });
  }, [activeTab, user?.id, user?.must_change_password, user?.role]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || activeTab !== "admin") return;
    const intervalId = window.setInterval(() => {
      loadAdminData().catch(() => {});
    }, 30000);
    return () => window.clearInterval(intervalId);
  }, [activeTab, user?.id, user?.must_change_password, user?.role]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role === "admin" || !swapDate) return;
    apiFetch(`/api/schedule/day?target_date=${swapDate}`)
      .then((payload) => {
        setDaySchedule(payload);
        setSourceChoice(null);
        setCandidateWeekOffset(0);
        setCandidateResults({ 0: null, 1: null });
      })
      .catch((error) => {
        setDaySchedule(null);
        setSourceChoice(null);
        setCandidateWeekOffset(0);
        setCandidateResults({ 0: null, 1: null });
        setBootStatus(extractErrorMessage(error));
        setStatusTone("error");
      });
  }, [swapDate, user?.id, user?.must_change_password, user?.role]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role === "admin" || !coverageDate) return;
    apiFetch(`/api/coverage/sources?date=${coverageDate}`)
      .then((payload) => {
        setCoverageSources(payload);
        setCoverageSourceChoice(null);
        setCoverageCandidateWeekOffset(0);
        setCoverageCandidateTab("available");
        setCoverageCandidateResults({ 0: null, 1: null });
      })
      .catch((error) => {
        setCoverageSources(null);
        setCoverageSourceChoice(null);
        setCoverageCandidateWeekOffset(0);
        setCoverageCandidateTab("available");
        setCoverageCandidateResults({ 0: null, 1: null });
        setBootStatus(extractErrorMessage(error));
        setStatusTone("error");
      });
  }, [coverageDate, user?.id, user?.must_change_password, user?.role]);

  const refreshAll = async () => {
    if (!user || user.must_change_password) return;
    await loadCommonData(user, weeklyDate);
    await loadWeeklyPlan(planDate);
    if (user.role === "admin") {
      return;
    }
    if (swapDate) {
      const dayPayload = await apiFetch(`/api/schedule/day?target_date=${swapDate}`);
      setDaySchedule(dayPayload);
    }
    if (coverageDate) {
      const sourcePayload = await apiFetch(`/api/coverage/sources?date=${coverageDate}`);
      setCoverageSources(sourcePayload);
    }
  };

  const handleLogin = async () => {
    try {
      const payload = await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(loginForm),
      });
      setUser(payload.user);
      setActiveTab(payload.user.role === "admin" ? "admin" : "dashboard");
      setLoginForm({ username: "", password: "" });
      setBootStatus("");
      if (!payload.user.must_change_password) {
        await loadCommonData(payload.user);
        await loadWeeklyPlan();
      }
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const handlePasswordChange = async () => {
    try {
      const payload = await apiFetch("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify(passwordForm),
      });
      setUser(payload.user);
      setActiveTab(payload.user.role === "admin" ? "admin" : "dashboard");
      setPasswordForm({ current_password: "", new_password: "" });
      setBootStatus("비밀번호가 변경되었습니다.");
      setStatusTone("success");
      await loadCommonData(payload.user);
      await loadWeeklyPlan();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const handleLogout = async () => {
    await apiFetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    setWeekly(null);
    setSwapRequests({ received: [], sent: [] });
    setCoverageRequests({ received: [], sent: [] });
    setSourceChoice(null);
    setCandidateWeekOffset(0);
    setCandidateResults({ 0: null, 1: null });
    setCoverageSources(null);
    setCoverageSourceChoice(null);
    setCoverageCandidateWeekOffset(0);
    setCoverageCandidateTab("available");
    setCoverageCandidateResults({ 0: null, 1: null });
    setNotifications({ items: [] });
    setWeeklyPlan(null);
    setAdminTimetable({ slots: [] });
    setActiveTab("dashboard");
    setBootStatus("");
  };

  const loadCandidates = async (period, weekOffset = candidateWeekOffset) => {
    try {
      setSourceChoice(period);
      setCandidateWeekOffset(weekOffset);
      const [thisWeekPayload, nextWeekPayload] = await Promise.all(
        swapCandidateWeekTabs.map((tab) =>
          apiFetch(`/api/swaps/candidates?date=${swapDate}&period=${period}&week_offset=${tab.value}`),
        ),
      );
      setCandidateResults({ 0: thisWeekPayload, 1: nextWeekPayload });
      setBootStatus("");
    } catch (error) {
      setCandidateResults({ 0: null, 1: null });
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const changeCandidateWeekOffset = (weekOffset) => {
    setCandidateWeekOffset(weekOffset);
    if (!sourceChoice) {
      setCandidateResults({ 0: null, 1: null });
      return;
    }
  };

  const submitSwapRequest = async (candidate) => {
    try {
      await apiFetch("/api/swaps/requests", {
        method: "POST",
        body: JSON.stringify({
          source_date: swapDate,
          source_period: sourceChoice,
          target_date: candidate.target_date,
          target_period: candidate.target_period,
        }),
      });
      setSourceChoice(null);
      setCandidateWeekOffset(0);
      setCandidateResults({ 0: null, 1: null });
      await refreshAll();
      setBootStatus("교체 요청을 전송했습니다. 해당 수업은 요청 중으로 잠금 처리됩니다.");
      setStatusTone("success");
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const loadCoverageTeachers = async (source) => {
    const selectedSource = source || coverageSourceChoice;
    if (!selectedSource) {
      setBootStatus("먼저 보강이 필요한 내 수업을 선택해 주세요.");
      setStatusTone("error");
      return;
    }
    try {
      setCoverageSourceChoice(selectedSource);
      setCoverageCandidateWeekOffset(0);
      setCoverageCandidateTab("available");
      const [thisWeekPayload, nextWeekPayload] = await Promise.all(
        swapCandidateWeekTabs.map((tab) =>
          apiFetch(
            `/api/coverage/candidates?date=${selectedSource.date}&period=${selectedSource.period}&week_offset=${tab.value}`,
          ),
        ),
      );
      setCoverageCandidateResults({ 0: thisWeekPayload, 1: nextWeekPayload });
      setBootStatus("");
      setStatusTone("info");
    } catch (error) {
      setCoverageCandidateResults({ 0: null, 1: null });
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const changeCoverageCandidateWeekOffset = (weekOffset) => {
    setCoverageCandidateWeekOffset(weekOffset);
    if (!coverageSourceChoice) {
      setCoverageCandidateResults({ 0: null, 1: null });
      return;
    }
  };

  const submitCoverageRequest = async (teacher) => {
    if (!coverageSourceChoice) {
      setBootStatus("먼저 보강이 필요한 내 수업을 선택해 주세요.");
      setStatusTone("error");
      return;
    }
    try {
      await apiFetch("/api/coverage/requests", {
        method: "POST",
        body: JSON.stringify({
          class_date: teacher.target_date,
          period: teacher.target_period,
          responder_id: teacher.teacher_id,
        }),
      });
      await refreshAll();
      setCoverageSourceChoice(null);
      setCoverageCandidateWeekOffset(0);
      setCoverageCandidateTab("available");
      setCoverageCandidateResults({ 0: null, 1: null });
      setBootStatus("보강 요청을 전송했습니다.");
      setStatusTone("success");
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const respondSwap = async (swapRequestId, action) => {
    const note = window.prompt("메모가 있으면 입력해 주세요. 없으면 빈칸으로 두셔도 됩니다.", "") || "";
    try {
      await apiFetch(`/api/swaps/requests/${swapRequestId}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note }),
      });
      setBootStatus(action === "accept" ? "교체 요청을 수락했습니다." : "교체 요청을 거절했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const respondCoverage = async (coverageRequestId, action) => {
    const note = window.prompt("메모가 있으면 입력해 주세요. 없으면 빈칸으로 두셔도 됩니다.", "") || "";
    try {
      await apiFetch(`/api/coverage/requests/${coverageRequestId}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note }),
      });
      setBootStatus(action === "accept" ? "보강 요청을 수락했습니다." : "보강 요청을 거절했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const dismissSentSwap = async (swapRequestId) => {
    try {
      await apiFetch(`/api/swaps/requests/${swapRequestId}/dismiss`, { method: "POST" });
      setBootStatus("확인한 교체 요청을 목록에서 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const dismissSentCoverage = async (coverageRequestId) => {
    try {
      await apiFetch(`/api/coverage/requests/${coverageRequestId}/dismiss`, { method: "POST" });
      setBootStatus("확인한 보강 요청을 목록에서 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const cancelPersonalSwap = async (swapRequestId) => {
    if (!window.confirm("이 교체 요청을 취소할까요? 확정된 교체라면 시간표 반영도 되돌아갑니다.")) return;
    try {
      await apiFetch(`/api/swaps/requests/${swapRequestId}/cancel`, { method: "POST" });
      setBootStatus("교체 요청을 취소했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const cancelPersonalCoverage = async (coverageRequestId) => {
    if (!window.confirm("이 보강 요청을 취소할까요? 확정된 보강이라면 시간표 반영도 되돌아갑니다.")) return;
    try {
      await apiFetch(`/api/coverage/requests/${coverageRequestId}/cancel`, { method: "POST" });
      setBootStatus("보강 요청을 취소했습니다. 상대 교사에게도 알림을 보냈습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const markNotifications = async () => {
    try {
      await apiFetch("/api/notifications/read", {
        method: "POST",
        body: JSON.stringify({ mark_all: true, notification_ids: [] }),
      });
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const deleteNotification = async (notificationId) => {
    try {
      await apiFetch("/api/notifications/delete", {
        method: "POST",
        body: JSON.stringify({ notification_ids: [notificationId], delete_read: false }),
      });
      setBootStatus("알림을 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const reloadAdminData = async () => {
    try {
      await loadAdminData();
      setBootStatus("관리자 교체 이력을 최신화했습니다.");
      setStatusTone("success");
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const checkImpact = async () => {
    try {
      const payload = await apiFetch("/api/admin/impact-check");
      setImpactReport(payload);
      setBootStatus(
        payload.summary.issue_count
          ? `영향도 검사 완료: ${payload.summary.issue_count}건의 확인 항목이 있습니다.`
          : "영향도 검사 완료: 감지된 충돌이 없습니다.",
      );
      setStatusTone(payload.summary.error_count ? "error" : payload.summary.warning_count ? "info" : "success");
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const previewFile = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const payload = await apiFetch("/api/admin/timetable/preview", {
        method: "POST",
        body: formData,
      });
      const missingTeacherActions = Object.fromEntries(
        (payload.preview.teacher_sync?.missing_teachers || []).map((teacher) => [teacher.id, "keep"]),
      );
      setPreviewState({ previewId: payload.preview_id, preview: payload.preview, corrections: {}, missingTeacherActions });
      setBootStatus("시간표 미리보기를 불러왔습니다.");
      setStatusTone("success");
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const confirmPreview = async () => {
    try {
      const corrections = Object.entries(previewState.corrections).map(([cell_ref, value]) => ({ cell_ref, value }));
      const missing_teacher_actions = Object.entries(previewState.missingTeacherActions || {}).map(
        ([teacher_id, action]) => ({ teacher_id: Number(teacher_id), action }),
      );
      const payload = await apiFetch("/api/admin/timetable/confirm", {
        method: "POST",
        body: JSON.stringify({
          preview_id: previewState.previewId,
          corrections,
          missing_teacher_actions,
        }),
      });
      const nextMissingTeacherActions = Object.fromEntries(
        (payload.preview.teacher_sync?.missing_teachers || []).map((teacher) => [teacher.id, "keep"]),
      );
      setPreviewState({
        previewId: previewState.previewId,
        preview: payload.preview,
        corrections: {},
        missingTeacherActions: nextMissingTeacherActions,
      });
      setImpactReport(null);
      setBootStatus("시간표를 확정했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const saveCalendar = async () => {
    try {
      const payload = await apiFetch("/api/admin/calendar-settings", {
        method: "PUT",
        body: JSON.stringify(calendarForm),
      });
      setCalendarForm(payload);
      setImpactReport(null);
      setBootStatus("학사일정을 저장했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const createTeacherAccount = async () => {
    try {
      await apiFetch("/api/admin/teachers", {
        method: "POST",
        body: JSON.stringify(newTeacher),
      });
      setNewTeacher({ display_name: "", username: "", role: "teacher" });
      setBootStatus("교사 계정을 만들었습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const updateTeacherAccount = async (teacherId, payload) => {
    try {
      await apiFetch(`/api/admin/teachers/${teacherId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setBootStatus("회원 정보를 수정했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
      throw error;
    }
  };

  const resetTeacher = async (teacherId) => {
    try {
      await apiFetch(`/api/admin/teachers/${teacherId}/reset-password`, { method: "POST" });
      setBootStatus("비밀번호를 초기값으로 초기화했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const removeTeacher = async (teacherId) => {
    if (!window.confirm("이 계정을 삭제할까요?")) return;
    try {
      await apiFetch(`/api/admin/teachers/${teacherId}`, { method: "DELETE" });
      setBootStatus("교사 계정을 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const createTimetableSlot = async (payload) => {
    try {
      await apiFetch("/api/admin/timetable/slots", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setImpactReport(null);
      setBootStatus("시간표 수업을 추가했습니다. 확정 교체·보강이 있다면 영향도 검사를 한 번 확인해 주세요.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
      throw error;
    }
  };

  const updateTimetableSlot = async (slotId, payload) => {
    try {
      await apiFetch(`/api/admin/timetable/slots/${slotId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setImpactReport(null);
      setBootStatus("시간표 수업을 수정했습니다. 확정 교체·보강이 있다면 영향도 검사를 한 번 확인해 주세요.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
      throw error;
    }
  };

  const deleteTimetableSlot = async (slotId) => {
    try {
      await apiFetch(`/api/admin/timetable/slots/${slotId}`, { method: "DELETE" });
      setImpactReport(null);
      setBootStatus("시간표 수업을 삭제했습니다. 확정 교체·보강이 있다면 영향도 검사를 한 번 확인해 주세요.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
      throw error;
    }
  };

  const rollbackSwap = async (swapRequestId) => {
    if (!window.confirm("확정된 교체를 취소할까요?")) return;
    try {
      await apiFetch(`/api/admin/swaps/${swapRequestId}/cancel`, { method: "POST" });
      setBootStatus("확정된 교체를 취소했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const rollbackCoverage = async (coverageRequestId) => {
    if (!window.confirm("확정된 보강 배정을 취소할까요?")) return;
    try {
      await apiFetch(`/api/admin/coverage/${coverageRequestId}/cancel`, { method: "POST" });
      setBootStatus("확정된 보강 배정을 취소했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const removeSwapHistory = async (swapRequestId) => {
    if (!window.confirm("이 교체 이력을 삭제할까요? 확정 상태라면 먼저 취소해야 합니다.")) return;
    try {
      await apiFetch(`/api/admin/swaps/${swapRequestId}`, { method: "DELETE" });
      setBootStatus("교체 이력을 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  const removeCoverageHistory = async (coverageRequestId) => {
    if (!window.confirm("이 보강 이력을 삭제할까요? 확정 상태라면 먼저 취소해야 합니다.")) return;
    try {
      await apiFetch(`/api/admin/coverage/${coverageRequestId}`, { method: "DELETE" });
      setBootStatus("보강 이력을 삭제했습니다.");
      setStatusTone("success");
      await refreshAll();
    } catch (error) {
      setBootStatus(extractErrorMessage(error));
      setStatusTone("error");
    }
  };

  if (!user) {
    return (
      <div className="auth-page">
        <div className="auth-frame">
          <div className="auth-hero glass">
            <p className="eyebrow">School Swap Desk</p>
            <h1>결보강 관리 시스템</h1>
            <p className="auth-lead">
              교체 요청, 보강 배정, 주간 반영, 계획서 작성까지 한곳에서 처리합니다.
            </p>
            <div className="auth-tags" aria-label="핵심 기능">
              <span>교체</span>
              <span>보강</span>
              <span>계획서</span>
            </div>
          </div>
          <div className="auth-card glass">
            <div>
              <h2 className="card-title">로그인</h2>
              <div className="muted">ID와 비밀번호를 입력해 주세요.</div>
            </div>
            <StatusBanner status={bootStatus} tone={statusTone} onDismiss={() => setBootStatus("")} />
            <div className="field-grid">
              <div className="field">
                <span className="field-title">ID</span>
                <input
                  className="input"
                  type="text"
                  value={loginForm.username}
                  onChange={(event) => setLoginForm((prev) => ({ ...prev, username: event.target.value }))}
                  placeholder="예: 이름 또는 admin"
                />
              </div>
              <div className="field">
                <span className="field-title">비밀번호</span>
                <input
                  className="input"
	                  type="password"
	                  value={loginForm.password}
	                  onChange={(event) => setLoginForm((prev) => ({ ...prev, password: event.target.value }))}
	                  placeholder="비밀번호"
	                />
              </div>
            </div>
            <div className="button-row">
              <button className="button primary" onClick={handleLogin}>
                로그인
              </button>
            </div>
            <div className="auth-note">
              관리자 ID: <strong>{health?.default_admin_username || "admin"}</strong>
              <br />
              초기 비밀번호는 학교 관리자 안내에 따라 입력하세요.
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (user.must_change_password) {
    return (
      <div className="auth-page">
        <div className="auth-frame">
          <div className="auth-hero glass">
            <p className="eyebrow">First Login</p>
            <h1>첫 로그인 보안 설정이 필요합니다</h1>
            <p>초기 비밀번호는 교사 전원에게 동일하므로, 서비스를 계속 사용하려면 먼저 새 비밀번호로 바꿔 주세요.</p>
          </div>
          <div className="auth-card glass">
            <div>
              <h2 className="card-title">비밀번호 변경</h2>
              <div className="muted">{user.display_name} 선생님, 첫 로그인 확인 단계입니다.</div>
            </div>
            <StatusBanner status={bootStatus} tone={statusTone} onDismiss={() => setBootStatus("")} />
            <div className="field-grid">
              <div className="field">
                <span className="field-title">현재 비밀번호</span>
                <input
                  className="input"
                  type="password"
                  value={passwordForm.current_password}
                  onChange={(event) =>
                    setPasswordForm((prev) => ({ ...prev, current_password: event.target.value }))
                  }
                />
              </div>
              <div className="field">
                <span className="field-title">새 비밀번호</span>
                <input
                  className="input"
                  type="password"
                  value={passwordForm.new_password}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, new_password: event.target.value }))}
                />
              </div>
            </div>
            <div className="button-row">
              <button className="button primary" onClick={handlePasswordChange}>
                변경 후 시작하기
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const tabs = isAdmin
    ? [
        { id: "admin", label: "관리자" },
        { id: "event", label: "행사 보강" },
        { id: "plan", label: "계획서 작성" },
      ]
    : [
        { id: "dashboard", label: "내 시간표" },
        { id: "swap", label: "교체 신청" },
        { id: "coverage", label: "보강 신청" },
        { id: "status", label: "교체·보강 현황" },
        { id: "plan", label: "계획서 작성" },
        { id: "inbox", label: `알림·요청함${unreadCount ? ` (${unreadCount})` : ""}` },
      ];

  const swapSourcePeriods =
    daySchedule?.periods?.filter((periodCell) => periodCell.status === "class" || periodCell.status === "locked") || [];
  const coverageSourcePeriods = coverageSources?.sources || [];
  const countCoverageCandidates = (result, candidateTab) =>
    (result?.slots || []).reduce(
      (sum, slot) => sum + (candidateTab === "available" ? slot.available_teachers.length : slot.busy_teachers.length),
      0,
    );
  const coverageVisibleTeachers = (coverageResult?.slots || []).flatMap((slot) => {
    const teachers = coverageCandidateTab === "available" ? slot.available_teachers : slot.busy_teachers;
    return teachers.map((teacher) => ({
      ...teacher,
      target_date: slot.date,
      target_day_label: slot.day_label,
      target_period: slot.period,
      target_class_code: slot.class_code,
      target_subject: slot.subject,
    }));
  });

  return (
    <div className="app-shell">
      <div className="main-shell">
        <aside className="sidebar glass">
          <div className="brand">
            <button
              type="button"
              className="brand-logo-button"
              aria-label="메인 홈으로 이동"
              onClick={() => changeTab(isAdmin ? "admin" : "dashboard")}
            >
              <BrandLogoIcon />
            </button>
            <h2>결보강 관리 시스템</h2>
            <p>경소마고 교사를 위한 업무공간</p>
          </div>
          <div className="profile-card">
            <div className="badge-row">
              <span className="role-pill">{user.role}</span>
              <span className="chip">{user.username}</span>
            </div>
            <h3 style={{ marginBottom: "6px" }}>{user.display_name}</h3>
            <small>{user.schedule_label || "시간표 계정"}</small>
          </div>
          <div className="tab-strip vertical">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`tab-button ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => changeTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="divider"></div>
          <div className="button-row">
            <button className="button ghost" onClick={refreshAll}>
              새로고침
            </button>
            <button className="button warn" onClick={handleLogout}>
              로그아웃
            </button>
          </div>
        </aside>

        <main className="content">
          <section className="main-hero campus-hero">
            <div className="campus-visual" aria-hidden="true">
              <div className="campus-building">
                <div className="school-sign">경북소프트웨어마이스터고등학교</div>
                <div className="building-windows">
                  {Array.from({ length: 18 }).map((_, index) => (
                    <span key={index}></span>
                  ))}
                </div>
              </div>
              <div className="campus-mascots">
                <span className="mascot mascot-blue"></span>
                <span className="mascot mascot-orange"></span>
                <span className="mascot-desk"></span>
              </div>
            </div>

            <div className="campus-content">
              <div className="hero-title-block">
                <span className="hero-pill">{user.display_name}</span>
                <p className="eyebrow">경북소프트웨어마이스터고등학교</p>
                <h1>수업 교체·보강</h1>
                <p className="panel-copy">수업의 교체와 보강 관리를 손쉽게</p>
              </div>
              <div className="hero-shortcuts" aria-label="빠른 이동">
                {tabs.map((tab) => (
                  <button
                    key={`hero-${tab.id}`}
                    className={`hero-shortcut ${activeTab === tab.id ? "active" : ""}`}
                    onClick={() => changeTab(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="hero-metrics">
                <div className="metric-card">
                  <div>기준 주</div>
                  <strong>{weeklyMeta.title}</strong>
                </div>
                {isAdmin ? (
                  <>
                    <div className="metric-card">
                      <div>교사 계정</div>
                      <strong>{teachers.length}</strong>
                    </div>
                    <div className="metric-card">
                      <div>교체·보강 이력</div>
                      <strong>{(adminSwaps.requests?.length || 0) + (adminSwaps.coverage_requests?.length || 0)}</strong>
                    </div>
                    <div className="metric-card">
                      <div>계획서 행</div>
                      <strong>{weeklyPlan?.summary?.row_count || 0}</strong>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="metric-card">
                      <div>받은 대기 요청</div>
                      <strong>
                        {swapRequests.received.filter((item) => item.status === "pending").length +
                          coverageRequests.received.filter((item) => item.status === "pending").length}
                      </strong>
                    </div>
                    <div className="metric-card">
                      <div>안 읽은 알림</div>
                      <strong>{unreadCount}</strong>
                    </div>
                    <div className="metric-card">
                      <div>주간 슬롯</div>
                      <strong>
                        {weekly?.days?.reduce(
                          (sum, day) =>
                            sum +
                            day.periods.filter((cell) => !["free", "holiday"].includes(statusTextForCell(cell))).length,
                          0,
                        ) || 0}
                      </strong>
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>

          <StatusBanner status={bootStatus} tone={statusTone} onDismiss={() => setBootStatus("")} />

          {activeTab === "dashboard" && !isAdmin ? (
            <div className="stack tab-panel-anchor" data-tab-panel="dashboard">
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>주간 반영본</h3>
                    <div className="week-meta">
                      <strong>{weeklyMeta.title}</strong>
                      <span>
                        {weeklyMeta.range} · {weeklyMeta.anchor}
                      </span>
                    </div>
                  </div>
                  <div className="week-controls">
                    <button className="button secondary" onClick={() => setWeeklyDate(addDays(weeklyDate, -7))}>
                      이전 주
                    </button>
                    <input
                      className="input"
                      type="date"
                      value={weeklyDate}
                      onChange={(event) => setWeeklyDate(event.target.value)}
                    />
                    <button className="button secondary" onClick={() => setWeeklyDate(addDays(weeklyDate, 7))}>
                      다음 주
                    </button>
                    <button className="button ghost" onClick={() => setWeeklyDate(today)}>
                      이번 주
                    </button>
                  </div>
                </div>
                <div className="panel-copy week-copy">교체와 보강 확정 결과를 주별로 확인합니다.</div>
                <WeeklyGrid weekly={weekly} />
              </div>
            </div>
          ) : null}

          {activeTab === "swap" && !isAdmin ? (
            <div className="grid-2 tab-panel-anchor" data-tab-panel="swap">
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>1. 날짜와 내 수업 선택</h3>
                    <div className="panel-copy">교체가 필요한 날짜를 고른 뒤, 내 정규수업을 선택하세요.</div>
                  </div>
                </div>
                <div className="field-grid">
                  <div className="field">
                    <span className="field-title">교체 희망일</span>
                    <input
                      className="input"
                      type="date"
                      value={swapDate}
                      onChange={(event) => setSwapDate(event.target.value)}
                    />
                  </div>
                </div>
                <div className="divider"></div>
                {!daySchedule ? (
                  <div className="empty">학기 일정이 아직 설정되지 않았거나 날짜를 불러오지 못했습니다.</div>
                ) : !daySchedule.is_school_day ? (
                  <div className="empty">선택한 날짜는 수업일이 아닙니다.</div>
                ) : swapSourcePeriods.length ? (
                  <div className="tableish">
                    {swapSourcePeriods.map((periodCell) => (
                      <div key={periodCell.period} className="list-card">
                        <div className="panel-header">
                          <div>
                            <strong>{periodCell.period}교시</strong>
                            <div className="panel-copy">{prettySlot(periodCell)}</div>
                            {periodCell.status === "locked" ? (
                              <div className="panel-copy">
                                {periodCell.lock_message || periodCell.lock_label || "이미 다른 요청과 겹칩니다."}
                              </div>
                            ) : null}
                          </div>
                          <button
                            className="button primary"
                            disabled={periodCell.status === "locked"}
                            onClick={() => loadCandidates(periodCell.period, candidateWeekOffset)}
                          >
                            {periodCell.status === "locked" ? "요청 중" : "후보 찾기"}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty">이 날엔 교체 가능한 정규수업이 없습니다.</div>
                )}
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>2. 교체 후보</h3>
                    <div className="panel-copy">
                      이번 주와 다음 주 후보를 나눠 보고, 같은 학반·상호 공강·순회/대기 요청 충돌 없음 조건을 통과한 수업만 표시합니다.
                    </div>
                  </div>
                </div>
                <div className="candidate-week-toolbar">
                  <div className="segmented-control" aria-label="교체 후보 주차">
                    {swapCandidateWeekTabs.map((option) => {
                      const result = candidateResults[option.value];
                      const countLabel = result ? `${result.candidates.length}건` : "조회 전";
                      return (
                      <button
                        key={option.value}
                        type="button"
                        className={candidateWeekOffset === option.value ? "active" : ""}
                        onClick={() => changeCandidateWeekOffset(option.value)}
                      >
                        <span>{option.label}</span>
                        <small>{countLabel}</small>
                      </button>
                    );
                    })}
                  </div>
                  {candidateResult?.week ? (
                    <span className="section-kicker">
                      {candidateResult.week.start_date} ~ {candidateResult.week.end_date}
                    </span>
                  ) : null}
                </div>
                {!hasCandidateSearch ? (
                  <div className="empty">왼쪽에서 내 수업을 선택하면 이번 주와 다음 주 후보를 한 번에 조회합니다.</div>
                ) : !candidateResult ? (
                  <div className="empty">선택한 주의 후보 정보를 불러오지 못했습니다. 다시 후보 찾기를 눌러 주세요.</div>
                ) : !candidateResult.candidates.length ? (
                  <div className="empty">{candidateResult.week?.label || "선택한 주"}에 조건을 만족하는 교체 후보가 없습니다.</div>
                ) : (
                  <div className="candidate-list">
                    <div className="candidate-source-summary">
                      <span>내 교체 대상 수업</span>
                      <strong>
                        {candidateResult.source.date} {candidateResult.source.day_label} {candidateResult.source.period}교시
                      </strong>
                      <em>
                        {candidateResult.source.class_code} · {candidateResult.source.subject}
                      </em>
                    </div>
                    {candidateResult.candidates.map((candidate) => (
                      <div
                        key={`${candidate.teacher_id}-${candidate.target_date}-${candidate.target_period}`}
                        className="request-card pending candidate-card"
                      >
                        <div className="panel-header">
                          <div>
                            <strong>{candidate.teacher_name}</strong>
                            <div className="panel-copy">교체 가능한 상대 수업</div>
                          </div>
                          <button className="button primary" onClick={() => submitSwapRequest(candidate)}>
                            요청 보내기
                          </button>
                        </div>
                        <div className="candidate-meta-grid">
                          <div>
                            <span>날짜</span>
                            <strong>{candidate.target_date}</strong>
                            <small>{candidate.target_day_label}요일 {candidate.target_period}교시</small>
                          </div>
                          <div>
                            <span>학반</span>
                            <strong>{candidate.class_code}</strong>
                            <small>같은 학반 조건 통과</small>
                          </div>
                          <div>
                            <span>과목</span>
                            <strong>{candidate.subject}</strong>
                            <small>{candidate.teacher_name} 담당</small>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {activeTab === "coverage" && !isAdmin ? (
            <div className="grid-2 tab-panel-anchor" data-tab-panel="coverage">
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>1. 보강할 내 수업 선택</h3>
                    <div className="panel-copy">날짜를 고른 뒤, 내 과목/학반 수업 중 보강이 필요한 수업을 선택하세요.</div>
                  </div>
                </div>
                <div className="field-grid">
                  <div className="field">
                    <span className="field-title">보강 날짜</span>
                    <input
                      className="input"
                      type="date"
                      value={coverageDate}
                      onChange={(event) => setCoverageDate(event.target.value)}
                    />
                  </div>
                </div>
                <div className="divider"></div>
                {!coverageSources ? (
                  <div className="empty">날짜의 내 수업을 불러오는 중입니다.</div>
                ) : !coverageSources.is_school_day ? (
                  <div className="empty">선택한 날짜는 수업일이 아닙니다.</div>
                ) : coverageSourcePeriods.length ? (
                  <div className="tableish">
                    {coverageSourcePeriods.map((source) => (
                      <div
                        key={`${source.date}-${source.period}-${source.class_code}-${source.subject}`}
                        className={`list-card coverage-source-card ${
                          coverageSourceChoice?.date === source.date &&
                          coverageSourceChoice?.period === source.period &&
                          coverageSourceChoice?.class_code === source.class_code &&
                          coverageSourceChoice?.subject === source.subject
                            ? "active"
                            : ""
                        }`}
                      >
                        <div className="panel-header">
                          <div>
                            <strong>{source.period}교시</strong>
                            <div className="panel-copy">
                              {source.class_code} {source.subject}
                            </div>
                            {source.locked ? (
                              <div className="tiny">이미 요청 또는 교체와 겹쳐 잠금 처리되었습니다.</div>
                            ) : null}
                          </div>
                          <button
                            className="button primary"
                            disabled={!source.can_request}
                            onClick={() => loadCoverageTeachers(source)}
                          >
                            보강 후보 찾기
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty">이 날엔 보강 요청을 보낼 내 정규수업이 없습니다.</div>
                )}
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>2. 보강 후보</h3>
                    <div className="panel-copy">
                      {coverageResult
                        ? `${coverageResult.week.label} · ${coverageResult.source.class_code} ${coverageResult.source.subject}`
                        : "선택한 수업의 같은 요일·교시에 비어 있는 교사를 이번 주/다음 주로 나눠 보여줍니다."}
                    </div>
                  </div>
                  {coverageResult ? (
                    <span className="chip">{countCoverageCandidates(coverageResult, "available")}명 가능</span>
                  ) : null}
                </div>
                {hasCoverageCandidateSearch ? (
                  <div className="candidate-week-toolbar">
                    <div className="segmented-control" aria-label="보강 후보 주차">
                      {swapCandidateWeekTabs.map((option) => {
                        const result = coverageCandidateResults[option.value];
                        const countLabel = result ? `${countCoverageCandidates(result, "available")}명 가능` : "조회 전";
                        return (
                          <button
                            key={option.value}
                            type="button"
                            className={coverageCandidateWeekOffset === option.value ? "active" : ""}
                            onClick={() => changeCoverageCandidateWeekOffset(option.value)}
                          >
                            <span>{option.label} 대상교사</span>
                            <small>{countLabel}</small>
                          </button>
                        );
                      })}
                    </div>
                    {coverageResult?.week ? (
                      <span className="section-kicker">
                        {coverageResult.week.start_date} ~ {coverageResult.week.end_date}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {coverageResult ? (
                  <div className="candidate-week-toolbar compact">
                    <div className="segmented-control" aria-label="보강 후보 상태">
                      {coverageCandidateTabs.map((option) => {
                        const count = countCoverageCandidates(coverageResult, option.value);
                        return (
                          <button
                            key={option.value}
                            type="button"
                            className={coverageCandidateTab === option.value ? "active" : ""}
                            onClick={() => setCoverageCandidateTab(option.value)}
                          >
                            <span>{option.label}</span>
                            <small>{count}명</small>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                {!hasCoverageCandidateSearch ? (
                  <div className="empty">내 수업 카드를 선택하면 이번 주와 다음 주 보강 후보를 한 번에 조회합니다.</div>
                ) : !coverageResult ? (
                  <div className="empty">선택한 주의 후보 정보를 불러오지 못했습니다. 다시 보강 후보 찾기를 눌러 주세요.</div>
                ) : (
                  <div className="candidate-list">
                    <div className="candidate-source-summary">
                      <span>선택한 보강 기준 수업</span>
                      <strong>
                        {coverageResult.source.date} {coverageResult.source.day_label} {coverageResult.source.period}교시
                      </strong>
                      <em>
                        {coverageResult.source.class_code} · {coverageResult.source.subject}
                      </em>
                    </div>
                    {!coverageVisibleTeachers.length ? (
                      <div className="empty">
                        {coverageCandidateTab === "available"
                          ? `${coverageResult.week.label}에 보강 가능한 교사가 없습니다.`
                          : `${coverageResult.week.label}에 수업 중인 교사가 없습니다.`}
                      </div>
                    ) : (
                      coverageVisibleTeachers.map((teacher) => {
                        const isAvailable = coverageCandidateTab === "available";
                        const statusText = teacher.status === "swapped-out" ? "교체로 비어 있음" : "공강";
                        const dayClassCount = teacher.day_class_count || 0;
                        const afterCoverageCount = isAvailable ? dayClassCount + 1 : dayClassCount;
                        const travelText = teacher.day_travel_count
                          ? `순회 ${teacher.day_travel_count}건 포함`
                          : "순회 없음";
                        return (
                          <div
                            key={`${coverageCandidateTab}-${teacher.target_date}-${teacher.target_period}-${teacher.teacher_id}`}
                            className={`request-card candidate-card coverage-candidate-card ${
                              isAvailable ? "pending" : "busy"
                            }`}
                          >
                            <div className="panel-header">
                              <div>
                                <strong>{teacher.teacher_name}</strong>
                                <div className="panel-copy">
                                  {isAvailable ? "보강 요청 가능" : "해당 시간 수업 중"}
                                </div>
                              </div>
                              {isAvailable ? (
                                <button className="button primary" onClick={() => submitCoverageRequest(teacher)}>
                                  보강 요청
                                </button>
                              ) : null}
                            </div>
                            <div className="candidate-meta-grid">
                              <div>
                                <span>날짜</span>
                                <strong>{teacher.target_date}</strong>
                                <small>{teacher.target_day_label}요일 {teacher.target_period}교시</small>
                              </div>
                              <div>
                                <span>보강 수업</span>
                                <strong>{teacher.target_class_code || "-"}</strong>
                                <small>{teacher.target_subject || "-"}</small>
                              </div>
                              <div>
                                <span>{isAvailable ? "현재 상태" : "현재 수업"}</span>
                                <strong>{isAvailable ? statusText : prettySlot(teacher.slot)}</strong>
                                <small>{teacher.username}</small>
                              </div>
                              <div>
                                <span>당일 수업량</span>
                                <strong>
                                  {isAvailable
                                    ? `${dayClassCount}건 → ${afterCoverageCount}건`
                                    : `${dayClassCount}건`}
                                </strong>
                                <small>{travelText}</small>
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {activeTab === "status" && !isAdmin ? (
            <PersonalStatusPanel
              user={user}
              swapRequests={swapRequests}
              coverageRequests={coverageRequests}
              onCancelSwap={cancelPersonalSwap}
              onCancelCoverage={cancelPersonalCoverage}
              onDismissSwap={dismissSentSwap}
              onDismissCoverage={dismissSentCoverage}
            />
          ) : null}

          {activeTab === "inbox" && !isAdmin ? (
            <div className="stack tab-panel-anchor" data-tab-panel="inbox">
              <NotificationPanel
                notifications={notifications}
                onMarkAll={markNotifications}
                onDeleteNotification={deleteNotification}
              />
              <div className="grid-2">
                <div className="panel">
                  <div className="panel-header">
                    <div>
                      <h3>받은 요청</h3>
                      <div className="panel-copy">상대 교사가 보낸 교체·보강 요청입니다.</div>
                    </div>
                  </div>
                  {!swapRequests.received.length && !coverageRequests.received.length ? (
                    <div className="empty">받은 요청이 없습니다.</div>
                  ) : (
                    <div className="tableish">
                      {coverageRequests.received.map((request) => (
                        <CoverageRequestCard
                          key={`coverage-${request.id}`}
                          request={request}
                          onAccept={request.status === "pending" ? (id) => respondCoverage(id, "accept") : null}
                          onReject={request.status === "pending" ? (id) => respondCoverage(id, "reject") : null}
                          onDismiss={
                            request.status !== "pending" && !request.responder_hidden ? dismissSentCoverage : null
                          }
                        />
                      ))}
                      {swapRequests.received.map((request) => (
                        <SwapRequestCard
                          key={`swap-${request.id}`}
                          request={request}
                          onAccept={request.status === "pending" ? (id) => respondSwap(id, "accept") : null}
                          onReject={request.status === "pending" ? (id) => respondSwap(id, "reject") : null}
                          onDismiss={request.status !== "pending" && !request.responder_hidden ? dismissSentSwap : null}
                        />
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel">
                  <div className="panel-header">
                    <div>
                      <h3>보낸 요청</h3>
                      <div className="panel-copy">내가 보낸 교체·보강 요청의 상태입니다.</div>
                    </div>
                  </div>
                  {!swapRequests.sent.length && !coverageRequests.sent.length ? (
                    <div className="empty">보낸 요청이 없습니다.</div>
                  ) : (
                    <div className="tableish">
                      {coverageRequests.sent.map((request) => (
                        <CoverageRequestCard
                          key={`coverage-${request.id}`}
                          request={request}
                          onDismiss={request.status === "pending" ? null : dismissSentCoverage}
                        />
                      ))}
                      {swapRequests.sent.map((request) => (
                        <SwapRequestCard
                          key={`swap-${request.id}`}
                          request={request}
                          onDismiss={request.status === "pending" ? null : dismissSentSwap}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {activeTab === "plan" ? (
            <PlanPanel
              planDate={planDate}
              setPlanDate={setPlanDate}
              weeklyPlan={weeklyPlan}
              isAdmin={isAdmin}
              onReloadPlan={() =>
                loadWeeklyPlan(planDate)
                  .then(() => {
                    setBootStatus("계획서 내역을 조회했습니다.");
                    setStatusTone("success");
                  })
                  .catch((error) => {
                    setBootStatus(extractErrorMessage(error));
                    setStatusTone("error");
                  })
              }
            />
          ) : null}

          {activeTab === "event" && isAdmin ? (
            <EventCoveragePanel teachers={teachers} onComplete={refreshAll} />
          ) : null}

          {activeTab === "admin" && isAdmin ? (
            <div className="tab-panel-anchor" data-tab-panel="admin">
              <AdminPanel
                health={health}
                previewState={previewState}
                onPreviewFile={previewFile}
                onCorrectionChange={(cellRef, value) =>
                  setPreviewState((prev) => ({
                    ...prev,
                    corrections: {
                      ...prev.corrections,
                      [cellRef]: value,
                    },
                  }))
                }
                onMissingTeacherActionChange={(teacherId, action) =>
                  setPreviewState((prev) => ({
                    ...prev,
                    missingTeacherActions: {
                      ...(prev.missingTeacherActions || {}),
                      [teacherId]: action,
                    },
                  }))
                }
                onConfirmPreview={confirmPreview}
                calendarForm={calendarForm}
                setCalendarForm={setCalendarForm}
                onSaveCalendar={saveCalendar}
                teachers={teachers}
                newTeacher={newTeacher}
                setNewTeacher={setNewTeacher}
                onCreateTeacher={createTeacherAccount}
                onUpdateTeacher={updateTeacherAccount}
                onResetTeacher={resetTeacher}
                onDeleteTeacher={removeTeacher}
                adminTimetable={adminTimetable}
                onCreateTimetableSlot={createTimetableSlot}
                onUpdateTimetableSlot={updateTimetableSlot}
                onDeleteTimetableSlot={deleteTimetableSlot}
                adminSwaps={adminSwaps}
                onReloadAdminData={reloadAdminData}
                onCancelAcceptedSwap={rollbackSwap}
                onCancelAcceptedCoverage={rollbackCoverage}
                onDeleteSwapRequest={removeSwapHistory}
                onDeleteCoverageRequest={removeCoverageHistory}
                impactReport={impactReport}
                onCheckImpact={checkImpact}
              />
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
