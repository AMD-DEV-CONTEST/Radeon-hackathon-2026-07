using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class NewsTicker : MonoBehaviour
{
    [SerializeField] private TextMeshProUGUI tickerText;
    [SerializeField] private float scrollSpeed = 150f;
    
    // The separator between different headlines
    [SerializeField] private string separator = "   ///   "; 

    private RectTransform textRectTransform;
    private float textWidth;
    private float containerWidth;

    void Awake()
    {
        textRectTransform = tickerText.GetComponent<RectTransform>();
    }

    // Call this from ShowRunner once the JSON is loaded!
    public void StartTicker(List<string> headlines)
    {
        // 1. Combine the headlines
        string combinedText = string.Join(separator, headlines) + separator;
        
        // (Optional) Duplicate the text so it wraps seamlessly without empty space
        tickerText.text = combinedText + combinedText; 

        // 2. Force mesh update to calculate the exact width of the new text
        tickerText.ForceMeshUpdate();
        textWidth = tickerText.preferredWidth / 2f; // Divide by 2 because we duplicated it

        // 3. Stretch the RectTransform width so the text stays on one single line
        textRectTransform.sizeDelta = new Vector2(tickerText.preferredWidth, textRectTransform.sizeDelta.y);

        // 4. Get the width of the screen/container
        containerWidth = textRectTransform.parent.GetComponent<RectTransform>().rect.width;

        // 5. Start the text on the far right edge of the screen
        Vector2 startPos = textRectTransform.anchoredPosition;
        startPos.x = containerWidth;
        textRectTransform.anchoredPosition = startPos;
    }

    void Update()
    {
        if (textWidth <= 0) return;

        // Slide the text to the left
        textRectTransform.anchoredPosition += Vector2.left * scrollSpeed * Time.deltaTime;

        // If the first chunk of text has moved completely off screen, loop it back
        if (textRectTransform.anchoredPosition.x < -textWidth)
        {
            Vector2 resetPos = textRectTransform.anchoredPosition;
            resetPos.x += textWidth; 
            textRectTransform.anchoredPosition = resetPos;
        }
    }
}