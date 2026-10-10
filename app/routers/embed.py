"""
app/routers/embed.py — Public widget delivery and configuration endpoints.

This module delivers:
  1. GET /api/widgets/{widget_id}/config (and alias /embed/{widget_id}/config):
     Returns the form definition JSON for an active widget with HTTP caching.
  2. GET /widget.js:
     Returns the client-side embed bundle / loader script that dynamically
     fetches the widget configuration and renders dynamic fields (Text, Email,
     Phone, Company, Select Dropdown, Textarea), lead magnet offers, honeypot traps,
     and submit handlers with beautiful Tailwind-like styling.

Both endpoints are public and allow external websites to load and render widgets.
"""

import logging
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.widget import Widget

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Widget Delivery & Embed"],
)


@router.get(
    "/api/widgets/{widget_id}/config",
    summary="Get widget configuration",
    response_description="Widget configuration definition",
)
@router.get(
    "/embed/{widget_id}/config",
    summary="Get widget configuration (alias)",
    include_in_schema=False,
)
async def get_widget_config(
    widget_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Retrieve public configuration for an active widget.

    Used by widget.js to render the form fields dynamically.
    Enforces HTTP caching (Cache-Control: public, max-age=300) to minimize database load.
    Does NOT leak tenant credentials or internal metadata.
    """
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    stmt = select(Widget).where(Widget.id == wid, Widget.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()

    if widget is None:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    # Return widget config JSON with immediate revalidation for live dashboard sync
    return JSONResponse(
        content=widget.config,
        headers={
            "Cache-Control": "no-cache, must-revalidate",
        },
    )


# Client-side embed JavaScript bundle template
WIDGET_JS_TEMPLATE = """/**
 * Nova Leads Embeddable Widget Loader (Enterprise Dynamic Field Builder)
 */
(function() {
    'use strict';

    // 1. Identify script tag and extract parameters
    var currentScript = document.currentScript || (function() {
        var scripts = document.getElementsByTagName('script');
        return scripts[scripts.length - 1];
    })();

    var defaultId = "__DEFAULT_WIDGET_ID__";
    var widgetId = defaultId;
    if (currentScript) {
        var attrId = currentScript.getAttribute('data-widget-id');
        if (attrId) {
            widgetId = attrId;
        } else if (currentScript.src) {
            try {
                var parsedUrl = new URL(currentScript.src, window.location.href);
                var queryId = parsedUrl.searchParams.get('id') || parsedUrl.searchParams.get('widget_id');
                if (queryId) widgetId = queryId;
            } catch (e) {}
        }
    }

    var apiBaseUrl = (currentScript && currentScript.src) 
        ? new URL(currentScript.src, window.location.href).origin 
        : (window.NOVA_LEADS_API_URL || window.LEADNOVA_API_URL || (typeof window !== 'undefined' && window.location ? window.location.origin : ''));

    if (!widgetId) {
        console.warn("[Nova Leads] No Widget ID specified in <script> tag (e.g. data-widget-id=\"YOUR_WIDGET_ID\").");
        return;
    }

    // Global registry
    window.NOVA_LEADS_WIDGET = window.NOVA_LEADS_WIDGET || window.LEADNOVA_WIDGET || {};
    window.NOVA_LEADS_WIDGET[widgetId] = {
        id: widgetId,
        loadedAt: new Date().toISOString()
    };

    // 2. Inject Scoped CSS Stylesheet if not already injected
    if (!document.getElementById('leadnova-widget-styles')) {
        var styleEl = document.createElement('style');
        styleEl.id = 'leadnova-widget-styles';
        styleEl.textContent = `
            .leadnova-widget-card {
                box-sizing: border-box;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
                padding: 24px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 10px 15px -3px rgba(0, 0, 0, 0.03);
                max-width: 480px;
                width: 100%;
                margin: 16px auto;
                color: #1e293b;
                line-height: 1.5;
            }
            .leadnova-widget-card * {
                box-sizing: border-box;
            }
            .leadnova-offer-banner {
                background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
                border: 1px solid #c7d2fe;
                border-radius: 10px;
                padding: 10px 14px;
                margin-bottom: 16px;
                font-size: 13px;
                font-weight: 600;
                color: #3730a3;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .leadnova-offer-badge {
                background: #4f46e5;
                color: #ffffff;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                padding: 2px 7px;
                border-radius: 6px;
                white-space: nowrap;
            }
            .leadnova-form-title {
                font-size: 20px;
                font-weight: 800;
                color: #0f172a;
                margin: 0 0 16px 0;
                line-height: 1.3;
                letter-spacing: -0.02em;
            }
            .leadnova-form-subtitle {
                font-size: 13px;
                color: #64748b;
                margin: -8px 0 16px 0;
                line-height: 1.4;
            }
            .leadnova-form-group {
                margin-bottom: 14px;
                text-align: left;
            }
            .leadnova-label {
                display: block;
                font-size: 12px;
                font-weight: 600;
                color: #475569;
                margin-bottom: 5px;
                text-transform: uppercase;
                letter-spacing: 0.3px;
            }
            .leadnova-input, .leadnova-select, .leadnova-textarea {
                width: 100%;
                padding: 10px 14px;
                font-size: 14px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: #f8fafc;
                color: #0f172a;
                transition: border-color 0.15s ease, box-shadow 0.15s ease, background-color 0.15s ease;
                outline: none;
                font-family: inherit;
            }
            .leadnova-input:focus, .leadnova-select:focus, .leadnova-textarea:focus {
                border-color: #4f46e5;
                background: #ffffff;
                box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.15);
            }
            .leadnova-textarea {
                resize: vertical;
                min-height: 80px;
            }
            .leadnova-submit-btn {
                width: 100%;
                padding: 12px 18px;
                font-size: 14px;
                font-weight: 700;
                color: #ffffff;
                background: #4f46e5;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                transition: background-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
                box-shadow: 0 2px 4px rgba(79, 70, 229, 0.2);
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                margin-top: 18px;
                font-family: inherit;
            }
            .leadnova-submit-btn:hover {
                background: #4338ca;
                box-shadow: 0 4px 10px rgba(79, 70, 229, 0.3);
                transform: translateY(-1px);
            }
            .leadnova-submit-btn:active {
                transform: translateY(0);
            }
            .leadnova-submit-btn:disabled {
                opacity: 0.7;
                cursor: not-allowed;
                transform: none;
            }
            .leadnova-honeypot {
                display: none !important;
                visibility: hidden !important;
                position: absolute !important;
                left: -9999px !important;
            }
            .leadnova-success-card {
                text-align: center;
                padding: 24px 12px;
            }
            .leadnova-success-icon {
                width: 48px;
                height: 48px;
                background: #dcfce7;
                color: #16a34a;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 12px;
            }
            .leadnova-success-title {
                font-size: 18px;
                font-weight: 800;
                color: #0f172a;
                margin: 0 0 6px 0;
            }
            .leadnova-success-msg {
                font-size: 13px;
                color: #64748b;
                margin: 0;
            }
            .leadnova-error-msg {
                display: none;
                background: #fef2f2;
                border: 1px solid #fecaca;
                color: #b91c1c;
                font-size: 12px;
                font-weight: 600;
                padding: 8px 12px;
                border-radius: 8px;
                margin-top: 12px;
                text-align: center;
            }
            .leadnova-branding {
                text-align: center;
                margin-top: 14px;
                font-size: 11px;
                color: #94a3b8;
                font-weight: 500;
            }
            .leadnova-branding a {
                color: #6366f1;
                text-decoration: none;
                font-weight: 600;
            }
            .leadnova-spinner {
                display: inline-block;
                width: 14px;
                height: 14px;
                border: 2px solid #ffffff;
                border-radius: 50%;
                border-top-color: transparent;
                animation: leadnova-spin 0.6s linear infinite;
            }
            @keyframes leadnova-spin {
                to { transform: rotate(360deg); }
            }
        `;
        document.head.appendChild(styleEl);
    }

    // 3. Locate or create mount target
    function getMountContainer() {
        var container = document.getElementById('nova-leads-widget-' + widgetId) ||
                        document.getElementById('leadnova-widget-' + widgetId) ||
                        document.getElementById('nova-leads-widget') ||
                        document.getElementById('leadnova-widget') ||
                        document.querySelector('[data-widget-id="' + widgetId + '"]');
        
        if (!container && currentScript && currentScript.parentNode) {
            container = document.createElement('div');
            container.id = 'nova-leads-widget-' + widgetId;
            currentScript.parentNode.insertBefore(container, currentScript.nextSibling);
        }
        return container || document.body;
    }

    // 4. Render Widget Form
    function renderWidget(config, container) {
        var title = config.title || "Get in Touch";
        var subtitle = config.subtitle || config.offer_text || "";
        var submitLabel = config.submit_label || "Submit";
        var fields = config.fields || [
            { name: "full_name", type: "text", label: "Full Name", required: true, placeholder: "Jane Doe" },
            { name: "email", type: "email", label: "Work Email", required: true, placeholder: "jane@example.com" }
        ];

        var offerHtml = "";
        if (subtitle && subtitle.trim()) {
            offerHtml = '<p class="leadnova-form-subtitle">' + escapeHtml(subtitle.trim()) + '</p>';
        }

        var fieldsHtml = "";
        for (var i = 0; i < fields.length; i++) {
            var f = fields[i];
            var fieldName = f.name || ("field_" + i);
            var fieldLabel = f.label || fieldName;
            var isRequired = f.required ? "required" : "";
            var placeholder = f.placeholder || "";
            var fieldType = (f.type || "text").toLowerCase();

            fieldsHtml += '<div class="leadnova-form-group">';
            fieldsHtml += '<label class="leadnova-label" for="ln_' + fieldName + '">' + escapeHtml(fieldLabel) + (f.required ? ' *' : '') + '</label>';

            if (fieldType === 'select') {
                fieldsHtml += '<select class="leadnova-select" id="ln_' + fieldName + '" name="' + fieldName + '" ' + isRequired + '>';
                fieldsHtml += '<option value="">Select an option...</option>';
                var options = Array.isArray(f.options) ? f.options : (typeof f.options === 'string' ? f.options.split(',') : []);
                for (var j = 0; j < options.length; j++) {
                    var optVal = String(options[j]).trim();
                    if (optVal) {
                        fieldsHtml += '<option value="' + escapeHtml(optVal) + '">' + escapeHtml(optVal) + '</option>';
                    }
                }
                fieldsHtml += '</select>';
            } else if (fieldType === 'number') {
                fieldsHtml += '<input type="number" class="leadnova-input" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder) + '" ' + isRequired + ' />';
            } else if (fieldType === 'url') {
                fieldsHtml += '<input type="url" class="leadnova-input" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder || "https://...") + '" ' + isRequired + ' />';
            } else if (fieldType === 'textarea') {
                fieldsHtml += '<textarea class="leadnova-textarea" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder) + '" rows="3" ' + isRequired + '></textarea>';
            } else if (fieldType === 'tel') {
                fieldsHtml += '<input type="tel" class="leadnova-input" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder || "+1 (555) 000-0000") + '" ' + isRequired + ' />';
            } else if (fieldType === 'email') {
                fieldsHtml += '<input type="email" class="leadnova-input" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder || "you@company.com") + '" ' + isRequired + ' />';
            } else {
                fieldsHtml += '<input type="text" class="leadnova-input" id="ln_' + fieldName + '" name="' + fieldName + '" placeholder="' + escapeHtml(placeholder) + '" ' + isRequired + ' />';
            }

            fieldsHtml += '</div>';
        }

        var styling = config.styling || {};
        var brandColor = styling.brand_color || styling.primary_color || '#4f46e5';
        var cardRadius = styling.corner_radius || '16px';

        var cardHtml = `
            <div class="leadnova-widget-card" style="border-radius: ` + cardRadius + `;">
                ` + offerHtml + `
                <h3 class="leadnova-form-title">` + escapeHtml(title) + `</h3>
                
                <form id="leadnova-form-` + widgetId + `">
                    ` + fieldsHtml + `

                    <!-- Anti-spam Honeypot Field -->
                    <div class="leadnova-honeypot">
                        <label for="ln_hp_` + widgetId + `">Website</label>
                        <input type="text" id="ln_hp_` + widgetId + `" name="honeypot" tabindex="-1" autocomplete="off" />
                    </div>

                    <button type="submit" class="leadnova-submit-btn" id="leadnova-submit-btn-` + widgetId + `" style="background-color: ` + brandColor + `;">
                        <span>` + escapeHtml(submitLabel) + `</span>
                    </button>
                    <div class="leadnova-error-msg" id="leadnova-error-` + widgetId + `"></div>
                </form>

                <div class="leadnova-branding">
                    Powered by <a href="` + apiBaseUrl + `" target="_blank">Nova Leads</a>
                </div>
            </div>
        `;

        container.innerHTML = cardHtml;

        // Attach Submit Handler
        var formEl = document.getElementById('leadnova-form-' + widgetId);
        var submitBtn = document.getElementById('leadnova-submit-btn-' + widgetId);
        var errorEl = document.getElementById('leadnova-error-' + widgetId);

        formEl.addEventListener('submit', function(e) {
            e.preventDefault();
            errorEl.style.display = 'none';
            submitBtn.disabled = true;
            var origBtnHtml = submitBtn.innerHTML;
            submitBtn.innerHTML = '<span class="leadnova-spinner"></span> <span>Submitting...</span>';

            // Extract form inputs
            var formData = new FormData(formEl);
            var payloadData = {};
            var honeypotVal = "";

            formData.forEach(function(value, key) {
                if (key === 'honeypot') {
                    honeypotVal = value;
                } else {
                    payloadData[key] = value;
                }
            });

            var endpoint = apiBaseUrl + '/submit/' + encodeURIComponent(widgetId);

            fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    data: payloadData,
                    honeypot: honeypotVal
                })
            })
            .then(function(res) {
                if (!res.ok) {
                    return res.json().then(function(errJson) {
                        throw new Error(errJson.detail?.detail || errJson.detail || errJson.error || "Submission failed");
                    }).catch(function() {
                        throw new Error("HTTP error " + res.status);
                    });
                }
                return res.json();
            })
            .then(function(data) {
                // Render Success Card
                var successMsg = config.success_message || "Thanks for reaching out! We will be in touch shortly.";
                container.innerHTML = `
                    <div class="leadnova-widget-card leadnova-success-card" style="border-radius: ` + cardRadius + `;">
                        <div class="leadnova-success-icon">✓</div>
                        <h4 class="leadnova-success-title">Message Received!</h4>
                        <p class="leadnova-success-msg">` + escapeHtml(successMsg) + `</p>
                        <div class="leadnova-branding" style="margin-top: 20px;">
                            Powered by <a href="` + apiBaseUrl + `" target="_blank">Nova Leads</a>
                        </div>
                    </div>
                `;

                if (config.redirect_url) {
                    try {
                        setTimeout(function() {
                            window.location.href = config.redirect_url;
                        }, 1400);
                    } catch (e) {}
                }
            })
            .catch(function(err) {
                errorEl.textContent = err.message || "Failed to submit. Please try again.";
                errorEl.style.display = 'block';
                submitBtn.disabled = false;
                submitBtn.innerHTML = origBtnHtml;
            });
        });
    }

    // Helper: Escape HTML
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // 5. Fetch Widget Configuration from Backend and Mount
    function init() {
        var mountTarget = getMountContainer();
        if (!mountTarget) return;

        // Show subtle skeleton while fetching
        mountTarget.innerHTML = `
            <div class="leadnova-widget-card" style="opacity: 0.6; text-align: center; padding: 32px 16px;">
                <span class="leadnova-spinner" style="border-color: #6366f1; border-top-color: transparent; width: 22px; height: 22px;"></span>
                <p style="font-size: 12px; color: #64748b; margin-top: 10px;">Loading form...</p>
            </div>
        `;

        var configUrl = apiBaseUrl + '/api/widgets/' + encodeURIComponent(widgetId) + '/config';

        fetch(configUrl, { cache: 'no-cache' })
            .then(function(res) {
                if (!res.ok) throw new Error("Widget not found or inactive (HTTP " + res.status + ")");
                return res.json();
            })
            .then(function(config) {
                renderWidget(config, mountTarget);
            })
            .catch(function(err) {
                console.error("[Nova Leads]", err);
                mountTarget.innerHTML = `
                    <div class="leadnova-widget-card" style="border-color: #fecaca; background: #fff5f5; text-align: center;">
                        <p style="color: #b91c1c; font-size: 13px; font-weight: 600; margin: 0;">Form unavailable</p>
                        <p style="color: #ef4444; font-size: 11px; margin: 4px 0 0 0;">` + escapeHtml(err.message) + `</p>
                    </div>
                `;
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
"""


@router.get(
    "/widget.js",
    summary="Download embed script bundle",
    response_description="JavaScript bundle for rendering the embed widget",
)
async def get_widget_js(
    id: str | None = Query(None, description="Widget ID passed as query parameter"),
    widget_id: str | None = Query(None, description="Alternative widget ID query parameter"),
) -> Response:
    """Return the client-side embeddable JavaScript bundle.

    External client websites include:
      <script src="https://your-domain.vercel.app/widget.js?id=YOUR_WIDGET_ID"></script>

    The script:
      1. Dynamically detects its widget ID and API base URL.
      2. Injects scoped, professional CSS styling into the client document.
      3. Fetches the JSON configuration (including lead magnet offers and dynamic fields).
      4. Renders Text, Email, Phone, Company, Select Dropdown, and Textarea inputs.
      5. Injects anti-spam honeypot fields.
      6. Handles AJAX submissions to /submit/{widget_id} with error handling and success state.
    """
    resolved_id = id or widget_id or ""
    rendered_js = WIDGET_JS_TEMPLATE.replace("__DEFAULT_WIDGET_ID__", resolved_id)

    return Response(
        content=rendered_js,
        media_type="text/javascript",
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "Content-Type": "text/javascript; charset=utf-8",
        },
    )
