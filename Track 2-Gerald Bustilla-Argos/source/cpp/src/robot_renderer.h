#pragma once
#include <d2d1.h>
#include <wrl/client.h>
#include <string>

using Microsoft::WRL::ComPtr;

enum class RobotState {
    Idle,
    Walking,
    Greeting,
    Working,
    Celebrating,
    Sleeping,
    Spinning
};

enum class ClickRegion {
    None,
    Head,   // face screen → input dialog
    Arms,   // side arms → wave
    Bottom  // lower body → walk (EVE hovers, no legs)
};

// Eye expressions — gives EVE some personality beyond a static stare.
enum class EyeExpression {
    Neutral,
    Happy,
    Curious,
    Surprised,
    Suspicious,
    Wink
};

class RobotRenderer {
public:
    RobotRenderer();
    ~RobotRenderer();

    bool Initialize(HWND hwnd);
    void Render();
    void Update();
    void OnResize(int width, int height);

    // Mouse handling — unified press/drag/click
    void OnMouseDown(int mouseX, int mouseY);
    void OnMouseMove(int mouseX, int mouseY);
    void OnMouseUp(int mouseX, int mouseY);

    bool IsDragging() const { return m_dragging; }
    bool WantsInputDialog() const { return m_wantsInputDialog; }
    void ClearInputDialogFlag() { m_wantsInputDialog = false; }
    void SetThinking(bool thinking) { m_thinking = thinking; }
    void SetExecutingTools(bool executing) { m_executingTools = executing; }

    float GetRobotScreenX() const { return m_screenX; }
    float GetRobotScreenY() const { return m_screenY; }

private:
    HWND m_hwnd = nullptr;
    ComPtr<ID2D1Factory> m_factory;
    ComPtr<ID2D1HwndRenderTarget> m_target;

    // Brushes — EVE palette: glossy white, black, neon blue, green plant
    ComPtr<ID2D1SolidColorBrush> m_brushWhite;        // body
    ComPtr<ID2D1SolidColorBrush> m_brushWhiteLight;   // highlight
    ComPtr<ID2D1SolidColorBrush> m_brushWhiteShade;   // soft shadow
    ComPtr<ID2D1SolidColorBrush> m_brushWhiteMid;     // mid gradient
    ComPtr<ID2D1SolidColorBrush> m_brushBlack;        // face screen
    ComPtr<ID2D1SolidColorBrush> m_brushNeon;        // blue LED eyes
    ComPtr<ID2D1SolidColorBrush> m_brushNeonBright;  // brighter blue
    ComPtr<ID2D1SolidColorBrush> m_brushNeonDim;     // dimmer blue
    ComPtr<ID2D1SolidColorBrush> m_brushPlant;        // green plant symbol
    ComPtr<ID2D1SolidColorBrush> m_brushShadow;      // ground shadow
    ComPtr<ID2D1SolidColorBrush> m_brushGlow;        // hover glow
    ComPtr<ID2D1SolidColorBrush> m_brushSpark;       // eye spark (always white)
    ComPtr<ID2D1SolidColorBrush> m_brushOutline;     // dark outline for bright backgrounds
    ComPtr<ID2D1SolidColorBrush> m_brushCape;        // yellow cape
    ComPtr<ID2D1SolidColorBrush> m_brushCapeShade;   // cape shadow
    ComPtr<ID2D1SolidColorBrush> m_brushCrest;       // Spartan crest (yellow-gold)
    ComPtr<ID2D1SolidColorBrush> m_brushPink;        // neon pink eyes
    ComPtr<ID2D1SolidColorBrush> m_brushPinkBright;  // brighter pink
    ComPtr<ID2D1SolidColorBrush> m_brushElectric;    // electric arc between head and body
    ComPtr<ID2D1SolidColorBrush> m_brushGreen;       // bright neon green eyes
    ComPtr<ID2D1SolidColorBrush> m_brushGreenBright; // yellow-green eye core
    ComPtr<ID2D1SolidColorBrush> m_brushGold;        // golden armor
    ComPtr<ID2D1SolidColorBrush> m_brushGoldLight;   // light gold highlight
    ComPtr<ID2D1SolidColorBrush> m_brushGoldDark;    // dark gold shade
    ComPtr<ID2D1SolidColorBrush> m_brushGoldMid;     // mid gold

    // Animation
    float m_animTime = 0.0f;
    RobotState m_state = RobotState::Idle;
    float m_stateTimer = 0.0f;
    float m_nextBehaviorTime = 3.0f;
    bool m_facingRight = true;

    // Eye expression (personality)
    EyeExpression m_eyeExpression = EyeExpression::Neutral;
    float m_eyeExprTimer = 6.0f;

    // Screen position
    float m_screenX = 50.0f;
    float m_screenY = 0.0f;  // 0 = bottom; positive = higher
    float m_targetX = 50.0f;
    float m_hoverSpeed = 100.0f;
    bool m_userWalking = false;

    // Spin state: arms revolve twice before walking
    float m_spinTimer = 0.0f;
    float m_spinDuration = 1.0f; // ~1s for 2 full revolutions
    bool m_spinWalkLeft = false;

    // Drag state
    bool m_mouseDown = false;
    bool m_dragging = false;
    int m_downX = 0, m_downY = 0;       // client coords at press
    int m_downScreenX = 0, m_downScreenY = 0; // screen coords at press
    float m_dragStartX = 0, m_dragStartY = 0; // robot pos at press
    float m_holdTimer = 0.0f;

    // Input dialog
    bool m_wantsInputDialog = false;

    // Typing detection
    float m_typingCooldown = 0.0f;
    float m_keyboardCheckTimer = 0.0f;
    bool m_lastKeyState[256] = {};
    HWND m_lastForegroundWnd = nullptr;

    // Adaptive color: dark body on bright backgrounds
    bool m_darkMode = false;
    float m_bgCheckTimer = 0.0f;

    // Thinking state (set during AI requests)
    bool m_thinking = false;

    // Tool execution state (electric lightning effect)
    bool m_executingTools = false;

    // Methods
    void PickNextBehavior();
    void SetState(RobotState state, float duration);
    void MoveWindowToRobot();
    void WalkToEdge(bool left);
    void StartSpinThenWalk(bool left);
    void CheckKeyboardActivity();
    float GetScreenLeftEdge();
    float GetScreenRightEdge();
    ClickRegion HitTest(int mouseX, int mouseY);
    float ComputeWalkLeanDeg() const;
    void SampleBackgroundBrightness();
    void UpdateColorScheme();

    // EVE drawing
    void DrawEggBody(float cx, float cy, float bob);
    void DrawHead(float cx, float headY, EyeExpression expr, bool sleeping, float turnOffsetX = 0.0f, bool showVisor = true);
    void DrawSingleEye(float ex, float ey, float halfW, float halfH, float rotationDeg);
    void DrawSeriousEye(float ex, float ey, bool left);
    void DrawHoverGlow(float cx, float baseY);
    void DrawArm(float cx, float cy, float bob, bool left, bool waving, float waveAngle,
                 float leanDeg = 0.0f, float dislocate = 0.0f, float squashX = 1.0f);
    void DrawSpinningArms(float cx, float cy, float bob, float spinAngle);
    void DrawGroundShadow(float cx, float baseY, float w);
    void DrawPlantSymbol(float cx, float cy);
    void DrawCape(float cx, float cy, float bob, float leanDeg);
    void DrawSpartanCrest(float cx, float headY);
    void DrawElectricArc(float cx, float neckY, float bodyY);
    void DrawToolLightning(float cx, float cy, float bob);
    void DrawShield(float cx, float cy, float bob, float leanDeg = 0.0f, float squashX = 1.0f);
    void DrawSword(float cx, float cy, float bob, bool waving = false, float waveAngle = 0.0f, float leanDeg = 0.0f, float dislocate = 0.0f, float squashX = 1.0f);
    void DrawGear(float cx, float cy, float r);
    void DrawRobot();
};
