/* Enhancements to editor.
 *
 * Editor runs smoothly even with JS disabled ;) */

(function(){
  function getFirst(o){return o && o[0]}
  
  var textInput = getFirst(document.getElementsByClassName('text-input'));
  var overTextInput = getFirst(document.getElementsByClassName('over-text-input'));

  // saving draft
  var autosaveInterval = null;

  page_info.editing = page_info.editing || {};
  
  overTextInput.innerHTML = [
    '<span class="oti-modified">&nbsp;</span>',
    '<span class="oti-charcount">? chars</span>',
    '<span class="oti-fontselect"><select><option value="sans">Sans-serif</option><option value="serif">Serif</option><option value="monospace">Monospace</option></select></span>',
    //'<span class="oti-linkpage">Link page</span>',
    '<span class="oti-draft">' + (localStorage.getItem('draft' + (page_info.editing.page_id || 'new')) !== null? '<a href="javascript:restoreDraft();">Draft found</a>': '') + '</span>'
  ].join(' ');

  // character counter
  var oldText = null, originalText = textInput.value;
  textInput.oninput = function(){
    var newText = textInput.value;
    if(newText != oldText){
      oldText = newText;

      overTextInput.children[0].innerHTML = newText === originalText? '&nbsp;' : '(*)';
      overTextInput.children[1].innerHTML = newText.length + ' char' + (newText.length == 1? '' : 's');
      if (!autosaveInterval) autosaveInterval = setInterval(autosaveText, 30000);
    }
  }
  overTextInput.children[1].innerHTML = originalText.length + ' char' + (originalText.length == 1? '' : 's');

  // change font of textarea
  var otiFontSelect = overTextInput.children[2].children[0];
  otiFontSelect.onchange = function(){
    textInput.className = textInput.className.replace(/\bti-font-\w+\b/, '') + ' ti-font-' + otiFontSelect.value;
  }; 

  // TODO link selector
  /*overTextInput.children[3].onclick = function(){
    
    }*/

  // url validation
  var urlInput = getFirst(document.getElementsByClassName('url-input'));
  urlInput.onchange = function(){
    if (!/^[a-z0-9-]*$/i.test(urlInput.value)) {
      urlInput.classList.add("error");
    } else {
      urlInput.classList.remove("error");
    }
  }

  // leave confirmation
  var saveButton = document.getElementById('save-button');
  saveButton.onclick = function(){
    window.onbeforeunload = null;
    localStorage.removeItem('draft' + (page_info.editing.page_id || 'new'));
  }
  var previewButton = document.getElementById('preview-button');
  previewButton.onclick = function(){
    window.onbeforeunload = null;
  }
  window.onbeforeunload = function(){
    if(oldText && oldText != originalText){
      return 'Are you sure you want to leave editing this page?';
    }
  }

  // TODO tag editor
  var tagsInput = getFirst(document.getElementsByClassName('tags-input'));

  // draft management
  function autosaveText(){
    localStorage.setItem('draft' + (page_info.editing.page_id || 'new'), textInput.value);
  }

  window.restoreDraft = function(){
    textInput.value = localStorage.getItem('draft' + (page_info.editing.page_id || 'new'));
    overTextInput.querySelector('.oti-draft').innerHTML = '';
  }
})();
