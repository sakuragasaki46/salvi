(function() {

  for (let i of document.getElementsByClassName('spoiler')) {
    i.onclick = function() {
      this.classList.toggle('revealed');
    }
  };
})();
